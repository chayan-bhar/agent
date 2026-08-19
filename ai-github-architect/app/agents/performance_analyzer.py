"""
Performance Analyzer Agent.

Identifies performance anti-patterns, bottlenecks, and optimization opportunities.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.graph.state import RepositoryAnalysisState
from app.utils.token_counter import format_files_for_prompt


class PerformanceFinding(BaseModel):
    title: str
    description: str
    severity: str = Field(description="CRITICAL | HIGH | MEDIUM | LOW | INFO")
    category: str = Field(
        description="N_PLUS_ONE | MISSING_CACHE | MISSING_PAGINATION | "
                    "BLOCKING_IO | EXPENSIVE_COMPUTATION | CONNECTION_POOL | "
                    "MISSING_INDEX | BATCH_OPPORTUNITY | MEMORY | OTHER"
    )
    confidence: str = Field(description="HIGH | MEDIUM | LOW")
    evidence_files: list[str]
    evidence_snippet: str | None = None
    impact: str
    recommendation: str
    estimated_improvement: str | None = Field(
        default=None,
        description="Estimated performance improvement if fixed (e.g. '80% reduction in DB queries')"
    )


class PerformanceAnalysisOutput(BaseModel):
    findings: list[PerformanceFinding]
    caching_present: bool | None = Field(default=None, description="Is any caching implemented?")
    caching_technology: str | None = None
    pagination_present: bool | None = None
    async_processing: bool | None = Field(default=None, description="Async/background job processing?")
    connection_pooling: bool | None = None
    overall_performance_risk: str = Field(description="CRITICAL | HIGH | MEDIUM | LOW")
    summary: str = Field(description="2-3 sentence performance posture summary")
    confidence: str = Field(description="HIGH | MEDIUM | LOW")
    insufficient_evidence_areas: list[str] = Field(default_factory=list)


class PerformanceAnalyzerAgent(BaseAgent):
    """Identifies performance bottlenecks and anti-patterns."""

    node_name = "performance_analyzer"

    async def _run(self, state: RepositoryAnalysisState) -> dict[str, Any]:
        file_contents = state.get("file_contents", {})
        file_tree = state.get("file_tree", [])
        repo_summary = state.get("repository_summary", {})

        # Prioritize data access and service layer files
        perf_paths = [
            path for path in file_contents
            if any(kw in path.lower() for kw in [
                "repository", "service", "query", "database", "db", "dao",
                "store", "cache", "controller", "handler", "route", "job",
                "task", "worker", "batch", "migration", "schema",
            ])
        ]
        other_paths = [p for p in file_contents if p not in perf_paths]

        content_items = (
            [(p, file_contents[p]) for p in perf_paths]
            + [(p, file_contents[p]) for p in other_paths]
        )
        formatted_contents = format_files_for_prompt(
            content_items,
            total_budget=18000,
            per_file_max=3000,
        )

        all_paths = "\n".join(f["path"] for f in file_tree)
        system_prompt = self._load_prompt("performance_analyzer")

        user_prompt = f"""
## Repository Context
- Repository: {state.get('repository_name', 'Unknown')}
- Type: {repo_summary.get('type', 'Unknown')}
- Technologies: {repo_summary.get('technologies', [])}
- Database types: {repo_summary.get('database_types', [])}
- Primary Language: {repo_summary.get('primary_language', 'Unknown')}

## All Repository Files
{all_paths}

## File Contents for Performance Analysis
{formatted_contents}

Analyze for performance issues. Focus on data access patterns, caching, and I/O operations.
Only flag issues with concrete evidence from the files above.
"""

        analysis = await self._llm.complete_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_schema=PerformanceAnalysisOutput,
            temperature=0.0,
        )

        return {
            "performance_analysis": analysis.model_dump(),
        }
