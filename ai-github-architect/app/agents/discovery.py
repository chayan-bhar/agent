"""
Repository Discovery Node.

First node in the workflow. Responsible for:
1. Fetching repository metadata via GitHub MCP
2. Building a scored, filtered file tree
3. Selecting the most relevant files for LLM analysis
4. Fetching content for selected files (within token budget)

This node does NOT call the LLM — it only interacts with the GitHub MCP server.
The output of this node feeds into all downstream analysis agents.
"""
from __future__ import annotations

from typing import Any, Optional

from app.agents.base import BaseAgent
from app.graph.state import FileEntry, RepositoryAnalysisState, RepositoryMetadata
from app.mcp.client import MCPClient
from app.services.llm.provider import LLMProvider
from app.utils.file_filter import FilePriority, FileRelevanceScorer
from app.utils.logging import get_logger
from app.utils.token_counter import budget_files

logger = get_logger(__name__)


class RepositoryDiscoveryAgent(BaseAgent):
    """
    Discovers and fetches repository structure without LLM involvement.

    Uses the GitHub MCP server for all data fetching.
    """

    node_name = "repository_discovery"

    def __init__(self, llm: LLMProvider, mcp_client: MCPClient) -> None:
        super().__init__(llm)
        self._mcp = mcp_client
        self._scorer = FileRelevanceScorer()

    async def _run(self, state: RepositoryAnalysisState) -> dict[str, Any]:
        owner = state["owner"]
        repo = state["repo"]
        analysis_id = state.get("analysis_id", "unknown")

        logger.info("discovery_starting", owner=owner, repo=repo, analysis_id=analysis_id)

        # ── 1. Fetch repository metadata ──────────────────────────────────────
        repo_info = await self._mcp.call_tool(
            "github", "get_repository_info",
            {"owner": owner, "repo": repo},
            cache_ttl=3600,
        )
        languages = await self._mcp.call_tool(
            "github", "get_languages",
            {"owner": owner, "repo": repo},
            cache_ttl=3600,
        )

        metadata: RepositoryMetadata = {
            "name": repo_info.get("name", repo),
            "full_name": repo_info.get("full_name", f"{owner}/{repo}"),
            "description": repo_info.get("description"),
            "default_branch": repo_info.get("default_branch", "main"),
            "primary_language": repo_info.get("language"),
            "languages": languages or {},
            "topics": repo_info.get("topics", []),
            "size_kb": repo_info.get("size_kb", 0),
            "stars": repo_info.get("stars", 0),
            "forks": repo_info.get("forks", 0),
            "license": repo_info.get("license", {}).get("name") if repo_info.get("license") else None,
            "created_at": repo_info.get("created_at"),
            "updated_at": repo_info.get("updated_at"),
            "html_url": repo_info.get("html_url", f"https://github.com/{owner}/{repo}"),
            "has_ci": False,      # Updated after tree scan
            "has_docker": False,
            "has_kubernetes": False,
            "has_tests": False,
        }

        # ── 2. Build directory tree ───────────────────────────────────────────
        tree_data = await self._mcp.call_tool(
            "github", "get_directory_tree",
            {"owner": owner, "repo": repo, "max_depth": 5, "max_files": 500},
            cache_ttl=3600,
        )

        raw_files: list[tuple[str, int]] = [
            (f["path"], f.get("size_bytes", 0))
            for f in tree_data.get("tree", [])
        ]

        # ── 3. Score and filter files ─────────────────────────────────────────
        scored = self._scorer.rank_and_filter(
            raw_files,
            max_files=150,
            min_priority=FilePriority.LOW,
        )

        file_tree: list[FileEntry] = [
            FileEntry(
                path=f.path,
                size_bytes=f.size_bytes,
                priority=f.priority.name,
                priority_reason=f.reason,
            )
            for f in scored
        ]

        # Update metadata flags based on file tree
        all_paths = {f.path.lower() for f in scored}
        metadata["has_ci"] = any(".github/workflows" in p for p in all_paths)
        metadata["has_docker"] = any("dockerfile" in p or "docker-compose" in p for p in all_paths)
        metadata["has_kubernetes"] = any(p.startswith(("k8s/", "helm/", "kubernetes/")) for p in all_paths)
        metadata["has_tests"] = any(p.startswith(("tests/", "test/", "spec/", "__tests__/")) for p in all_paths)

        # ── 4. Select files for LLM analysis (CRITICAL + HIGH + some MEDIUM) ─
        relevant = [f for f in scored if f.priority >= FilePriority.HIGH]
        if len(relevant) < 30:
            # Include MEDIUM files if we have budget
            relevant = [f for f in scored if f.priority >= FilePriority.MEDIUM]

        relevant_entries: list[FileEntry] = [
            FileEntry(
                path=f.path,
                size_bytes=f.size_bytes,
                priority=f.priority.name,
                priority_reason=f.reason,
            )
            for f in relevant[:80]  # Cap at 80 files
        ]

        # ── 5. Fetch file contents within token budget ─────────────────────────
        file_contents: dict[str, str] = {}
        files_to_fetch = [(f.path, f.size_bytes) for f in relevant[:50]]

        for path, _ in files_to_fetch:
            try:
                content_data = await self._mcp.call_tool(
                    "github", "get_file_content",
                    {"owner": owner, "repo": repo, "file_path": path},
                    cache_ttl=3600,
                )
                if content_data and not content_data.get("truncated"):
                    file_contents[path] = content_data.get("content", "")
            except Exception as exc:
                logger.warning(
                    "file_fetch_failed",
                    path=path,
                    error=str(exc),
                    analysis_id=analysis_id,
                )

        logger.info(
            "discovery_complete",
            owner=owner,
            repo=repo,
            total_files=len(file_tree),
            relevant_files=len(relevant_entries),
            fetched_files=len(file_contents),
            analysis_id=analysis_id,
        )

        return {
            "repository_metadata": metadata,
            "file_tree": file_tree,
            "relevant_files": relevant_entries,
            "file_contents": file_contents,
        }
