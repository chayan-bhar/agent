"""
Repository Analyzer Agent.

Analyzes the overall purpose, technology stack, major components,
and entry points of the repository using the LLM.

This is the second node in the workflow. It has access to the full
file tree and fetched file contents from the discovery node.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.graph.state import RepositoryAnalysisState
from app.utils.token_counter import format_files_for_prompt


class RepositorySummaryOutput(BaseModel):
    """Structured output for repository analysis."""

    purpose: str = Field(description="What this repository does in 2-3 sentences")
    type: str = Field(description="e.g. web-api, cli-tool, library, mobile-app, monorepo")
    maturity: str = Field(description="production | beta | prototype | abandoned")
    technologies: list[str] = Field(description="All technologies, frameworks, and tools used")
    primary_language: str = Field(description="Primary programming language")
    framework: str | None = Field(default=None, description="Primary web/application framework")
    entry_points: list[str] = Field(description="Main entry point files")
    major_modules: list[dict[str, str]] = Field(
        description="List of {name, path, description} for major modules/packages"
    )
    key_dependencies: list[dict[str, str]] = Field(
        description="Critical external dependencies with {name, purpose, version_hint}"
    )
    configuration_files: list[str] = Field(description="Important configuration files found")
    test_framework: str | None = Field(default=None, description="Testing framework used")
    build_tool: str | None = Field(default=None, description="Build tool or package manager")
    deployment_approach: str | None = Field(
        default=None,
        description="How the application is deployed (Docker, K8s, serverless, etc.)"
    )
    api_style: str | None = Field(
        default=None,
        description="REST, GraphQL, gRPC, WebSocket, or None"
    )
    database_types: list[str] = Field(
        default_factory=list,
        description="Database types used (PostgreSQL, MongoDB, Redis, etc.)"
    )
    confidence: str = Field(description="HIGH | MEDIUM | LOW confidence in analysis accuracy")
    insufficient_evidence_areas: list[str] = Field(
        default_factory=list,
        description="Areas where evidence was insufficient to make confident claims"
    )


class RepositoryAnalyzerAgent(BaseAgent):
    """Analyzes repository purpose, stack, and component structure."""

    node_name = "repository_analyzer"

    async def _run(self, state: RepositoryAnalysisState) -> dict[str, Any]:
        metadata = state.get("repository_metadata", {})
        file_tree = state.get("file_tree", [])
        file_contents = state.get("file_contents", {})

        # Build file listing for prompt
        file_listing = "\n".join(
            f"  {f['path']} ({f['priority']})"
            for f in file_tree[:100]
        )

        # Format most relevant file contents
        content_items = [
            (path, content)
            for path, content in file_contents.items()
        ]
        formatted_contents = format_files_for_prompt(
            content_items,
            total_budget=20000,
            per_file_max=3000,
        )

        system_prompt = self._load_prompt("repository_analyzer")

        user_prompt = f"""
## Repository Information
- Name: {metadata.get('full_name', 'Unknown')}
- Description: {metadata.get('description', 'No description')}
- Primary Language: {metadata.get('primary_language', 'Unknown')}
- Languages: {metadata.get('languages', {})}
- Topics: {metadata.get('topics', [])}
- Stars: {metadata.get('stars', 0)} | Forks: {metadata.get('forks', 0)}
- Size: {metadata.get('size_kb', 0)} KB
- Has CI: {metadata.get('has_ci', False)} | Has Docker: {metadata.get('has_docker', False)}
- Has Tests: {metadata.get('has_tests', False)}

## Repository File Structure ({len(file_tree)} files)
{file_listing}

## Key File Contents
{formatted_contents}

Analyze this repository and return a comprehensive JSON summary.
"""

        analysis = await self._llm.complete_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_schema=RepositorySummaryOutput,
        )

        return {
            "repository_summary": analysis.model_dump(),
        }
