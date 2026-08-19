"""
Improvement Planner Agent.

Synthesizes findings from all specialized analyzers into a prioritized,
evidence-backed improvement roadmap.

This agent runs AFTER all four parallel analyzers have completed.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.graph.state import Recommendation, RepositoryAnalysisState


class ImprovementRecommendationOutput(BaseModel):
    title: str
    description: str
    priority: str = Field(description="CRITICAL | HIGH | MEDIUM | LOW")
    category: str = Field(
        description="SECURITY | PERFORMANCE | ARCHITECTURE | CODE_QUALITY | "
                    "TESTING | DOCUMENTATION | DEVOPS | DEPENDENCIES"
    )
    impact: str = Field(description="Clear business/technical impact description")
    effort: str = Field(description="HIGH | MEDIUM | LOW (weeks/days/hours)")
    files: list[str] = Field(description="Specific repository files to change")
    suggested_solution: str = Field(description="Concrete, actionable steps")
    related_findings: list[str] = Field(
        default_factory=list,
        description="Finding titles from the analysis that this addresses"
    )


class ImprovementPlanOutput(BaseModel):
    recommendations: list[ImprovementRecommendationOutput]
    quick_wins: list[str] = Field(
        description="Top 3-5 highest-impact, lowest-effort improvements"
    )
    critical_actions: list[str] = Field(
        description="Items that must be addressed immediately (security/stability)"
    )
    roadmap_phases: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Suggested phased roadmap: [{phase, duration, items}]"
    )
    total_technical_debt_estimate: str = Field(
        description="Rough estimate of technical debt: e.g. '3-6 developer months'"
    )


class ImprovementPlannerAgent(BaseAgent):
    """Creates a prioritized improvement roadmap from all analysis findings."""

    node_name = "improvement_planner"

    async def _run(self, state: RepositoryAnalysisState) -> dict[str, Any]:
        repo_summary = state.get("repository_summary", {})
        arch_analysis = state.get("architecture_analysis", {})
        sec_analysis = state.get("security_analysis", {})
        perf_analysis = state.get("performance_analysis", {})
        qa_analysis = state.get("code_quality_analysis", {})
        revision_count = state.get("revision_count", 0)
        approval_feedback = state.get("approval_feedback")

        import json

        system_prompt = self._load_prompt("improvement_planner")

        # Build revision context if this is a revision cycle
        revision_context = ""
        if revision_count > 0 and approval_feedback:
            revision_context = f"""
## Human Reviewer Feedback (Revision #{revision_count})
Action: {approval_feedback.get('action', 'N/A')}
Feedback: {approval_feedback.get('feedback_text', 'No specific feedback')}
Instructions: {approval_feedback.get('revision_instructions', 'None')}

Please incorporate this feedback into your revised recommendations.
"""

        user_prompt = f"""
## Repository Context
- Repository: {state.get('repository_name', 'Unknown')}
- Type: {repo_summary.get('type', 'Unknown')}
- Technologies: {repo_summary.get('technologies', [])}
- Overall Security Risk: {sec_analysis.get('overall_risk_level', 'Unknown')}
- Overall Performance Risk: {perf_analysis.get('overall_performance_risk', 'Unknown')}
- Code Quality Score: {qa_analysis.get('overall_quality_score', 'Unknown')}
- Architectural Style: {arch_analysis.get('architectural_style', 'Unknown')}

## Security Findings Summary
{json.dumps(sec_analysis.get('findings', [])[:10], indent=2)}

## Performance Findings Summary
{json.dumps(perf_analysis.get('findings', [])[:10], indent=2)}

## Code Quality Issues Summary
{json.dumps(qa_analysis.get('issues', [])[:10], indent=2)}

## Architecture Issues
- Secondary patterns: {arch_analysis.get('secondary_patterns', [])}
- Scalability notes: {arch_analysis.get('scalability_notes', [])}

{revision_context}

Create a prioritized improvement plan. Maximum 15 recommendations.
Every recommendation must reference specific files from the repository.
Do NOT generate generic recommendations.
"""

        plan = await self._llm.complete_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_schema=ImprovementPlanOutput,
            temperature=0.1,
        )

        # Convert to state Recommendation format
        recommendations: list[Recommendation] = [
            Recommendation(
                title=r.title,
                description=r.description,
                priority=r.priority,
                category=r.category,
                impact=r.impact,
                effort=r.effort,
                files=r.files,
                suggested_solution=r.suggested_solution,
                related_findings=r.related_findings,
            )
            for r in plan.recommendations
        ]

        return {
            "improvement_recommendations": recommendations,
        }
