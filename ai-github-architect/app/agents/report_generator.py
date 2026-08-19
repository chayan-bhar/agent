"""
Report Generator Agent.

Generates the final professional Markdown report from all analysis outputs.
This is the penultimate node before human approval.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.agents.base import BaseAgent
from app.graph.state import RepositoryAnalysisState


class ReportGeneratorAgent(BaseAgent):
    """Generates the comprehensive Markdown architecture report."""

    node_name = "report_generator"

    async def _run(self, state: RepositoryAnalysisState) -> dict[str, Any]:
        metadata = state.get("repository_metadata", {})
        repo_summary = state.get("repository_summary", {})
        arch_analysis = state.get("architecture_analysis", {})
        sec_analysis = state.get("security_analysis", {})
        perf_analysis = state.get("performance_analysis", {})
        qa_analysis = state.get("code_quality_analysis", {})
        recommendations = state.get("improvement_recommendations", [])
        arch_diagram = state.get("architecture_diagram", "")
        data_flow_diagram = state.get("data_flow_diagram", "")
        file_tree = state.get("file_tree", [])

        system_prompt = self._load_prompt("report_generator")

        user_prompt = f"""
## Repository Information
- Name: {state.get('repository_name', 'Unknown')}
- URL: {state.get('repository_url', 'Unknown')}
- Description: {metadata.get('description', 'No description')}
- Stars: {metadata.get('stars', 0)} | Forks: {metadata.get('forks', 0)}
- License: {metadata.get('license', 'Unknown')}

## Repository Summary
{json.dumps(repo_summary, indent=2)}

## Architecture Analysis
{json.dumps(arch_analysis, indent=2)}

## Architecture Diagram (Mermaid)
{arch_diagram or 'Not available'}

## Data Flow Diagram
{data_flow_diagram or 'Not available'}

## Security Analysis
{json.dumps(sec_analysis, indent=2)}

## Performance Analysis
{json.dumps(perf_analysis, indent=2)}

## Code Quality Analysis
{json.dumps(qa_analysis, indent=2)}

## Improvement Recommendations
{json.dumps(recommendations, indent=2)}

## File Structure (top 50 files)
{chr(10).join(f['path'] for f in file_tree[:50])}

Generate the full professional Markdown report following the specified structure.
Every section must include evidence references to specific files.
Use the Mermaid diagrams exactly as provided — do not modify them.
"""

        report_markdown = await self._llm.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=8192,
        )

        # Add report header with metadata
        report_header = f"""---
**Repository**: [{state.get('repository_name', 'Unknown')}]({state.get('repository_url', '')})
**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
**Analysis ID**: `{state.get('analysis_id', 'N/A')}`

---

"""
        final_report = report_header + report_markdown

        report_metadata = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "analysis_id": state.get("analysis_id"),
            "repository": state.get("repository_name"),
            "word_count": len(final_report.split()),
            "character_count": len(final_report),
            "sections_generated": 20,
            "findings_count": {
                "security": len(sec_analysis.get("findings", [])),
                "performance": len(perf_analysis.get("findings", [])),
                "quality": len(qa_analysis.get("issues", [])),
                "recommendations": len(recommendations),
            },
        }

        return {
            "final_report": final_report,
            "report_metadata": report_metadata,
            "approval_status": "PENDING",
        }
