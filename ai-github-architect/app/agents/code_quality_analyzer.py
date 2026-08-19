"""
Code Quality Analyzer Agent.

Evaluates code quality, design pattern usage, SOLID violations,
and maintainability concerns.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.graph.state import RepositoryAnalysisState
from app.utils.token_counter import format_files_for_prompt


class QualityIssue(BaseModel):
    title: str
    description: str
    severity: str = Field(description="HIGH | MEDIUM | LOW")
    category: str = Field(
        description="SOLID | GOD_CLASS | LONG_METHOD | DUPLICATION | "
                    "COUPLING | NAMING | ERROR_HANDLING | TEST_COVERAGE | "
                    "ANTI_PATTERN | COMPLEXITY | DOCUMENTATION"
    )
    confidence: str = Field(description="HIGH | MEDIUM | LOW")
    evidence_files: list[str]
    specific_location: str | None = Field(
        default=None,
        description="Specific class/function name if identifiable"
    )
    recommendation: str
    impact: str


class DesignPattern(BaseModel):
    name: str
    usage: str = Field(description="CORRECT | INCORRECT | OVERUSED")
    evidence_files: list[str]
    description: str


class CodeQualityOutput(BaseModel):
    issues: list[QualityIssue]
    design_patterns_observed: list[DesignPattern]
    anti_patterns_observed: list[dict[str, str]] = Field(
        default_factory=list,
        description="Anti-patterns: {name, description, evidence_file}"
    )
    test_coverage_assessment: str = Field(
        description="GOOD | MODERATE | POOR | ABSENT | UNKNOWN"
    )
    test_quality_notes: list[str] = Field(default_factory=list)
    error_handling_quality: str = Field(
        description="GOOD | MODERATE | POOR | ABSENT | UNKNOWN"
    )
    code_complexity: str = Field(description="LOW | MODERATE | HIGH | UNKNOWN")
    documentation_quality: str = Field(description="GOOD | MODERATE | POOR | ABSENT | UNKNOWN")
    overall_quality_score: str = Field(description="A | B | C | D | F")
    summary: str = Field(description="2-3 sentence code quality summary")
    confidence: str = Field(description="HIGH | MEDIUM | LOW")
    insufficient_evidence_areas: list[str] = Field(default_factory=list)


class CodeQualityAnalyzerAgent(BaseAgent):
    """Evaluates code quality, patterns, and maintainability."""

    node_name = "code_quality_analyzer"

    async def _run(self, state: RepositoryAnalysisState) -> dict[str, Any]:
        file_contents = state.get("file_contents", {})
        file_tree = state.get("file_tree", [])
        repo_summary = state.get("repository_summary", {})

        # Focus on business logic and test files
        quality_paths = [
            path for path in file_contents
            if any(kw in path.lower() for kw in [
                "service", "controller", "handler", "domain", "model",
                "entity", "use_case", "usecase", "interactor", "manager",
                "factory", "builder", "test", "spec",
            ])
        ]
        other_paths = [p for p in file_contents if p not in quality_paths]

        content_items = (
            [(p, file_contents[p]) for p in quality_paths]
            + [(p, file_contents[p]) for p in other_paths]
        )
        formatted_contents = format_files_for_prompt(
            content_items,
            total_budget=20000,
            per_file_max=3500,
        )

        all_paths = "\n".join(f["path"] for f in file_tree)
        system_prompt = self._load_prompt("code_quality_analyzer")

        user_prompt = f"""
## Repository Context
- Repository: {state.get('repository_name', 'Unknown')}
- Type: {repo_summary.get('type', 'Unknown')}
- Primary Language: {repo_summary.get('primary_language', 'Unknown')}
- Technologies: {repo_summary.get('technologies', [])}
- Test Framework: {repo_summary.get('test_framework', 'Unknown')}

## All Repository Files
{all_paths}

## File Contents for Quality Analysis
{formatted_contents}

Evaluate code quality. For each issue, name the specific file, class, or function.
Only report what you can see in the provided files. Do not invent issues.
"""

        analysis = await self._llm.complete_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_schema=CodeQualityOutput,
            temperature=0.1,
        )

        return {
            "code_quality_analysis": analysis.model_dump(),
        }
