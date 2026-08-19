"""
MCP Client wrapper.

Provides a clean async interface for LangGraph agents to call MCP server tools
without knowing anything about the transport layer.

Architecture:
    Agent → MCPClient.call_tool(server, tool, args) → stdio → MCP Server

Redis caching is integrated here so tool results are cached transparently.
Agents never call GitHub API or Redis directly.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.mcp.registry import MCPServerSpec, get_registry
from app.utils.logging import get_logger
from app.utils.retry import with_retry

logger = get_logger(__name__)


class MCPClientError(Exception):
    """Raised when an MCP tool call fails after all retries."""

    def __init__(self, server: str, tool: str, reason: str) -> None:
        self.server = server
        self.tool = tool
        self.reason = reason
        super().__init__(f"MCP tool '{server}.{tool}' failed: {reason}")


class MCPClient:
    """
    Async client for calling tools on MCP servers.

    Each call_tool() invocation spawns a short-lived subprocess running
    the target MCP server, executes the tool, then tears down the process.

    This stateless approach is intentional for correctness in async contexts.
    For high-frequency usage the client should be extended with connection pooling.

    Usage:
        client = MCPClient()
        result = await client.call_tool("github", "get_repository_info",
                                        {"owner": "fastapi", "repo": "fastapi"})
    """

    def __init__(
        self,
        cache_service: Optional[Any] = None,
    ) -> None:
        """
        Args:
            cache_service: Optional CacheService for Redis caching.
                           If None, caching is disabled.
        """
        self._registry = get_registry()
        self._cache = cache_service

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        cache_ttl: Optional[int] = None,
    ) -> Any:
        """
        Call a tool on the named MCP server.

        Args:
            server_name: Registry name of the MCP server (e.g. "github").
            tool_name: Name of the tool to call (e.g. "get_file_content").
            arguments: Dict of tool arguments.
            cache_ttl: If provided and cache is configured, cache the result
                       for this many seconds.

        Returns:
            The tool's return value (deserialized from MCP response).

        Raises:
            MCPClientError: If the tool call fails.
            KeyError: If server_name is not in the registry.
        """
        spec = self._registry.get(server_name)

        # ── Cache lookup ──────────────────────────────────────────────────────
        cache_key: Optional[str] = None
        if self._cache and cache_ttl:
            cache_key = _build_cache_key(server_name, tool_name, arguments)
            cached = await self._cache.get(cache_key)
            if cached is not None:
                logger.debug(
                    "mcp_cache_hit",
                    server=server_name,
                    tool=tool_name,
                    cache_key=cache_key,
                )
                return cached

        # ── Execute tool ──────────────────────────────────────────────────────
        result = await self._execute_tool(spec, tool_name, arguments)

        # ── Cache store ───────────────────────────────────────────────────────
        if self._cache and cache_ttl and cache_key:
            await self._cache.set(cache_key, result, ttl=cache_ttl)

        return result

    async def _execute_tool(
        self,
        spec: MCPServerSpec,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Spawn the MCP server subprocess and call the tool."""
        server_params = StdioServerParameters(
            command=spec.command,
            args=spec.args,
            env=spec.env or None,
        )

        logger.info(
            "mcp_tool_calling",
            server=spec.name,
            tool=tool_name,
            args_keys=list(arguments.keys()),
        )

        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    response = await session.call_tool(tool_name, arguments)

                    if response.isError:
                        error_text = str(response.content)
                        logger.error(
                            "mcp_tool_error",
                            server=spec.name,
                            tool=tool_name,
                            error=error_text,
                        )
                        raise MCPClientError(spec.name, tool_name, error_text)

                    # Extract the actual result from MCP content blocks
                    result = _extract_result(response.content)

                    logger.info(
                        "mcp_tool_success",
                        server=spec.name,
                        tool=tool_name,
                    )
                    return result

        except MCPClientError:
            raise
        except Exception as exc:
            logger.error(
                "mcp_client_exception",
                server=spec.name,
                tool=tool_name,
                error=str(exc),
                exc_info=True,
            )
            raise MCPClientError(spec.name, tool_name, str(exc)) from exc


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_cache_key(server: str, tool: str, arguments: dict[str, Any]) -> str:
    """Build a deterministic Redis cache key for a tool call."""
    # Sort arguments to ensure key is stable regardless of dict ordering
    args_str = json.dumps(arguments, sort_keys=True)
    return f"mcp:{server}:{tool}:{hash(args_str) & 0xFFFFFFFF:08x}"


def _extract_result(content: list[Any]) -> Any:
    """
    Extract the Python value from MCP tool response content blocks.

    MCP returns a list of content blocks (TextContent, ImageContent, etc.).
    For tool calls that return dicts/lists, the content is JSON in a TextContent block.
    """
    if not content:
        return None

    if len(content) == 1:
        block = content[0]
        # TextContent block — may be JSON
        text = getattr(block, "text", None)
        if text is not None:
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return text

    # Multiple blocks — return as list of text
    return [getattr(b, "text", str(b)) for b in content]
