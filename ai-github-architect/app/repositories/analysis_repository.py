"""
Analysis and Report data access repositories.

These classes encapsulate all database queries. No SQL should appear
in service or API layers — only repository method calls.

Pattern: Repository per aggregate root (Analysis + Report, Feedback).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.analysis import Analysis, Feedback, Report
from app.utils.logging import get_logger

logger = get_logger(__name__)


# ── Analysis Repository ───────────────────────────────────────────────────────


class AnalysisRepository:
    """Data access for Analysis records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        analysis_id: str,
        repository_url: str,
        repository_name: str,
        owner: str,
        repo: str,
        langgraph_thread_id: str,
    ) -> Analysis:
        """Create and persist a new Analysis record."""
        analysis = Analysis(
            id=analysis_id,
            repository_url=repository_url,
            repository_name=repository_name,
            owner=owner,
            repo=repo,
            status="STARTED",
            langgraph_thread_id=langgraph_thread_id,
            progress="Analysis queued",
        )
        self._session.add(analysis)
        await self._session.flush()
        logger.info("analysis_created", analysis_id=analysis_id, repo=repository_name)
        return analysis

    async def get_by_id(self, analysis_id: str) -> Optional[Analysis]:
        """Fetch an analysis by ID, including its report."""
        result = await self._session.execute(
            select(Analysis)
            .options(selectinload(Analysis.report))
            .where(Analysis.id == analysis_id)
        )
        return result.scalar_one_or_none()

    async def get_by_thread_id(self, thread_id: str) -> Optional[Analysis]:
        """Fetch an analysis by its LangGraph thread ID."""
        result = await self._session.execute(
            select(Analysis).where(Analysis.langgraph_thread_id == thread_id)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        analysis_id: str,
        status: str,
        current_node: Optional[str] = None,
        progress: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update the status and progress of an analysis."""
        values: dict = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
        if current_node is not None:
            values["current_node"] = current_node
        if progress is not None:
            values["progress"] = progress
        if error_message is not None:
            values["error_message"] = error_message
        if status == "COMPLETED":
            values["completed_at"] = datetime.now(timezone.utc)

        await self._session.execute(
            update(Analysis).where(Analysis.id == analysis_id).values(**values)
        )
        logger.info(
            "analysis_status_updated",
            analysis_id=analysis_id,
            status=status,
            node=current_node,
        )

    async def update_analysis_outputs(
        self,
        analysis_id: str,
        state: dict,
    ) -> None:
        """
        Persist LangGraph state outputs to the database.

        Called after each major node completes so partial results are
        always saved, even if a later node fails.
        """
        values = {
            "updated_at": datetime.now(timezone.utc),
            "status": state.get("approval_status", "RUNNING"),
            "current_node": state.get("current_node"),
            "errors": state.get("errors", []),
            "warnings": state.get("warnings", []),
        }

        for field in (
            "repository_metadata",
            "repository_summary",
            "architecture_analysis",
            "security_analysis",
            "performance_analysis",
            "code_quality_analysis",
            "improvement_recommendations",
        ):
            if field in state:
                values[field] = state[field]

        await self._session.execute(
            update(Analysis).where(Analysis.id == analysis_id).values(**values)
        )

    async def list_recent(self, limit: int = 20) -> list[Analysis]:
        """Return the most recent analyses."""
        result = await self._session.execute(
            select(Analysis)
            .order_by(desc(Analysis.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())


# ── Report Repository ─────────────────────────────────────────────────────────


class ReportRepository:
    """Data access for Report records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_or_update(
        self,
        analysis_id: str,
        content: str,
        report_metadata: Optional[dict] = None,
    ) -> Report:
        """Create a report or update it if one already exists for this analysis."""
        result = await self._session.execute(
            select(Report).where(Report.analysis_id == analysis_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.content = content
            existing.report_metadata = report_metadata or {}
            existing.word_count = len(content.split())
            existing.updated_at = datetime.now(timezone.utc)
            logger.info("report_updated", analysis_id=analysis_id)
            return existing

        report = Report(
            analysis_id=analysis_id,
            content=content,
            word_count=len(content.split()),
            report_metadata=report_metadata or {},
        )
        self._session.add(report)
        await self._session.flush()
        logger.info("report_created", analysis_id=analysis_id)
        return report

    async def get_by_analysis_id(self, analysis_id: str) -> Optional[Report]:
        """Fetch the report for a given analysis."""
        result = await self._session.execute(
            select(Report).where(Report.analysis_id == analysis_id)
        )
        return result.scalar_one_or_none()


# ── Feedback Repository ───────────────────────────────────────────────────────


class FeedbackRepository:
    """Data access for human approval Feedback records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        analysis_id: str,
        action: str,
        feedback_text: Optional[str] = None,
        revision_instructions: Optional[str] = None,
        revision_number: int = 0,
    ) -> Feedback:
        """Record a human approval action."""
        feedback = Feedback(
            analysis_id=analysis_id,
            action=action,
            feedback_text=feedback_text,
            revision_instructions=revision_instructions,
            revision_number=revision_number,
        )
        self._session.add(feedback)
        await self._session.flush()
        logger.info(
            "feedback_recorded",
            analysis_id=analysis_id,
            action=action,
            revision=revision_number,
        )
        return feedback

    async def get_latest(self, analysis_id: str) -> Optional[Feedback]:
        """Return the most recent feedback for an analysis."""
        result = await self._session.execute(
            select(Feedback)
            .where(Feedback.analysis_id == analysis_id)
            .order_by(desc(Feedback.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()
