"""
MCP Server Registry.

Registry pattern that maps server names to their startup specifications.
Agents ask the registry for a server by name; the registry returns the
command/arguments needed to spawn the MCP server process.

This keeps the agent code entirely decoupled from which MCP servers exist.
Future servers (Jira, Slack, K8s, Confluence, etc.) can be registered here
without touching any agent code.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class MCPServerSpec:
    """Specification for launching a single MCP server via stdio transport."""

    name: str
    description: str
    command: str                  # Executable (e.g. "python")
    args: list[str]               # Arguments to the executable
    env: dict[str, str] = field(default_factory=dict)  # Additional env vars
    enabled: bool = True

    @property
    def full_command(self) -> list[str]:
        """Return the full command+args list for subprocess launch."""
        return [self.command, *self.args]


class MCPServerRegistry:
    """
    Registry of all available MCP servers.

    Usage:
        registry = MCPServerRegistry.default()
        spec = registry.get("github")
        # Use spec to launch the server via MCP client
    """

    def __init__(self) -> None:
        self._servers: dict[str, MCPServerSpec] = {}

    def register(self, spec: MCPServerSpec) -> "MCPServerRegistry":
        """Register a server spec. Returns self for chaining."""
        self._servers[spec.name] = spec
        return self

    def get(self, name: str) -> MCPServerSpec:
        """Return the spec for the given server name."""
        if name not in self._servers:
            available = ", ".join(self._servers.keys())
            raise KeyError(
                f"MCP server '{name}' not found in registry. "
                f"Available: [{available}]"
            )
        return self._servers[name]

    def list_enabled(self) -> list[MCPServerSpec]:
        """Return all enabled server specs."""
        return [s for s in self._servers.values() if s.enabled]

    @classmethod
    def default(cls) -> "MCPServerRegistry":
        """
        Build the default registry with all built-in MCP servers.

        Add new servers here when they are implemented. Agents never
        need to know this method exists.
        """
        registry = cls()

        # ── GitHub MCP Server ─────────────────────────────────────────────────
        registry.register(
            MCPServerSpec(
                name="github",
                description="GitHub repository tools: file tree, content, metadata, commits",
                command=sys.executable,
                args=["-m", "app.mcp.github_server.server"],
            )
        )

        # ── Future servers (not yet implemented) ──────────────────────────────
        # registry.register(MCPServerSpec(
        #     name="jira",
        #     description="Jira issue tracking tools",
        #     command=sys.executable,
        #     args=["-m", "app.mcp.jira_server.server"],
        #     enabled=False,
        # ))
        # registry.register(MCPServerSpec(
        #     name="kubernetes",
        #     description="Kubernetes cluster inspection tools",
        #     command=sys.executable,
        #     args=["-m", "app.mcp.kubernetes_server.server"],
        #     enabled=False,
        # ))

        return registry


# Module-level singleton
_default_registry: Optional[MCPServerRegistry] = None


def get_registry() -> MCPServerRegistry:
    """Return the shared MCP server registry singleton."""
    global _default_registry
    if _default_registry is None:
        _default_registry = MCPServerRegistry.default()
    return _default_registry
