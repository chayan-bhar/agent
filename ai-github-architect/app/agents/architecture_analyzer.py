"""
Architecture Analyzer Agent.

Identifies architectural style, component relationships, and data flows.
Generates a Mermaid diagram from actual repository evidence.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.graph.state import RepositoryAnalysisState
from app.utils.token_counter import format_files_for_prompt


class ArchitectureComponent(BaseModel):
    name: str
    type: str = Field(description="api | service | repository | database | queue | cache | ui | external")
    description: str
    files: list[str] = Field(description="Evidence files")
    technology: str | None = None


class ArchitectureAnalysisOutput(BaseModel):
    architectural_style: str = Field(
        description="Primary style: monolith | microservices | event-driven | hexagonal | clean | layered | serverless"
    )
    architectural_style_evidence: list[str] = Field(description="Files that support this classification")
    secondary_patterns: list[str] = Field(default_factory=list, description="Additional patterns observed")

    components: list[ArchitectureComponent] = Field(description="All identified components")
    layers: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Architectural layers: {name, description, components}"
    )

    dependencies: list[dict[str, str]] = Field(
        description="Component dependencies: {from, to, type (HTTP|event|direct|database)}"
    )

    entry_points: list[dict[str, str]] = Field(
        description="Application entry points: {path, type, description}"
    )

    mermaid_diagram: str = Field(
        description="Valid Mermaid flowchart TD diagram representing the architecture"
    )
    data_flow_diagram: str | None = Field(
        default=None,
        description="Optional second Mermaid diagram showing request/data flow"
    )

    scalability_notes: list[str] = Field(
        default_factory=list,
        description="Architectural observations relevant to scalability"
    )

    confidence: str = Field(description="HIGH | MEDIUM | LOW")
    insufficient_evidence_areas: list[str] = Field(default_factory=list)


class ArchitectureAnalyzerAgent(BaseAgent):
    """Analyzes and diagrams the software architecture."""

    node_name = "architecture_analyzer"

    async def _run(self, state: RepositoryAnalysisState) -> dict[str, Any]:
        metadata = state.get("repository_metadata", {})
        file_tree = state.get("file_tree", [])
        file_contents = state.get("file_contents", {})
        repo_summary = state.get("repository_summary", {})

        # Prioritize structural files for architecture analysis
        arch_relevant_paths = [
            path for path in file_contents
            if any(kw in path.lower() for kw in [
                "main", "app", "server", "config", "service", "controller",
                "router", "route", "handler", "repository", "repo", "docker",
                "compose", "k8s", "helm", "application", "bootstrap", "di",
                "container", "module", "factory", "setup",
            ])
        ]

        content_items = [
            (path, file_contents[path])
            for path in arch_relevant_paths
        ] + [
            (path, content)
            for path, content in file_contents.items()
            if path not in arch_relevant_paths
        ]

        formatted_contents = format_files_for_prompt(
            content_items,
            total_budget=18000,
            per_file_max=2500,
        )

        file_listing = "\n".join(f["path"] for f in file_tree[:120])

        system_prompt = self._load_prompt("architecture_analyzer")

        user_prompt = f"""
## Repository Context
{repo_summary.get('purpose', 'Unknown')}

- Type: {repo_summary.get('type', 'Unknown')}
- Primary Language: {metadata.get('primary_language', 'Unknown')}
- Framework: {repo_summary.get('framework', 'Unknown')}
- Technologies: {repo_summary.get('technologies', [])}
- Has Docker: {metadata.get('has_docker', False)}
- Has Kubernetes: {metadata.get('has_kubernetes', False)}

## File Structure
{file_listing}

## Key File Contents
{formatted_contents}

Analyze the architecture and generate:
1. Architectural style classification with evidence
2. Component map
3. Mermaid flowchart diagram (ONLY include real components)
4. Data flow description
"""

        analysis = await self._llm.complete_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_schema=ArchitectureAnalysisOutput,
        )

        result: dict[str, Any] = {
            "architecture_analysis": analysis.model_dump(),
        }

        # Extract diagrams into their own state keys for easy report access
        if analysis.mermaid_diagram:
            result["architecture_diagram"] = analysis.mermaid_diagram
        if analysis.data_flow_diagram:
            result["data_flow_diagram"] = analysis.data_flow_diagram

        return result
