"""
Security Analyzer Agent.

Scans repository code for security vulnerabilities, weaknesses, and risks.
Every finding is evidence-based — no vulnerability is claimed without proof.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.graph.state import RepositoryAnalysisState
from app.utils.token_counter import format_files_for_prompt


class SecurityFinding(BaseModel):
    title: str
    description: str
    severity: str = Field(description="CRITICAL | HIGH | MEDIUM | LOW | INFO")
    finding_type: str = Field(description="CONFIRMED | POTENTIAL | RECOMMENDATION")
    confidence: str = Field(description="HIGH | MEDIUM | LOW")
    category: str = Field(
        description="SECRETS | AUTHENTICATION | AUTHORIZATION | INJECTION | "
                    "DESERIALIZATION | CORS | CSRF | INPUT_VALIDATION | "
                    "SENSITIVE_DATA | DEPENDENCIES | CONFIGURATION"
    )
    evidence_files: list[str]
    evidence_snippet: str | None = None
    impact: str
    recommendation: str


class SecurityAnalysisOutput(BaseModel):
    findings: list[SecurityFinding]
    auth_mechanism: str | None = Field(
        default=None,
        description="Authentication mechanism used (JWT | OAuth | Session | API Key | None | Unknown)"
    )
    authorization_approach: str | None = Field(
        default=None,
        description="Authorization approach: RBAC | ABAC | custom | none | unknown"
    )
    secret_management: str | None = Field(
        default=None,
        description="How secrets are managed: env_vars | vault | hardcoded | unknown"
    )
    https_enforced: bool | None = Field(default=None, description="Is HTTPS enforced?")
    input_validation_present: bool | None = None
    overall_risk_level: str = Field(description="CRITICAL | HIGH | MEDIUM | LOW")
    summary: str = Field(description="2-3 sentence security posture summary")
    confidence: str = Field(description="HIGH | MEDIUM | LOW")
    insufficient_evidence_areas: list[str] = Field(default_factory=list)


class SecurityAnalyzerAgent(BaseAgent):
    """Identifies security vulnerabilities and risks."""

    node_name = "security_analyzer"

    async def _run(self, state: RepositoryAnalysisState) -> dict[str, Any]:
        file_contents = state.get("file_contents", {})
        file_tree = state.get("file_tree", [])
        repo_summary = state.get("repository_summary", {})

        # Prioritize security-relevant files
        security_paths = [
            path for path in file_contents
            if any(kw in path.lower() for kw in [
                "auth", "security", "jwt", "token", "oauth", "permission",
                "middleware", "cors", "csrf", "session", "password", "secret",
                "config", "env", "settings", "credential",
            ])
        ]
        other_paths = [p for p in file_contents if p not in security_paths]

        content_items = (
            [(p, file_contents[p]) for p in security_paths]
            + [(p, file_contents[p]) for p in other_paths]
        )
        formatted_contents = format_files_for_prompt(
            content_items,
            total_budget=20000,
            per_file_max=3000,
        )

        all_paths = "\n".join(f["path"] for f in file_tree)
        system_prompt = self._load_prompt("security_analyzer")

        user_prompt = f"""
## Repository Context
- Repository: {state.get('repository_name', 'Unknown')}
- Type: {repo_summary.get('type', 'Unknown')}
- Technologies: {repo_summary.get('technologies', [])}
- Has CI: {state.get('repository_metadata', {}).get('has_ci', False)}

## All Repository Files
{all_paths}

## File Contents for Security Analysis
{formatted_contents}

Perform a thorough security audit. For every finding, provide the specific file(s) as evidence.
If you cannot find evidence of a vulnerability, do NOT report it.
"""

        analysis = await self._llm.complete_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_schema=SecurityAnalysisOutput,
            temperature=0.0,  # Maximum determinism for security analysis
        )

        return {
            "security_analysis": analysis.model_dump(),
        }
