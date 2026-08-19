"""
Analysis Orchestration Service.

The single point of coordination between:
  - FastAPI endpoints
  - LangGraph workflow (running in background)
  - PostgreSQL (via AnalysisRepository)
  - Redis (via CacheService)
  - MCP client (passed to workflow)

Architecture principle:
  FastAPI routes should be thin. All business logic lives here.
  Routes call one service method and return the result.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.graph.state import ApprovalFeedback, initial_state
from app.graph.workflow import build_workflow
from app.models.database import get_db_session
from app.repositories.analysis_repository import (
    AnalysisRepository,
    FeedbackRepository,
    ReportRepository,
)
from app.services.cache_service import (
    CacheService,
    TTL_ANALYSIS_STATUS,
    analysis_status_key,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)


class AnalysisService:
    """
    Orchestrates the full analysis lifecycle.

    One instance per request (no shared state).
    """

    def __init__(self, cache: Optional[CacheService] = None) -> None:
        self._cache = cache

    async def start_analysis(
        self,
        repository_url: str,
        owner: str,
        repo: str,
    ) -> dict[str, Any]:
        """
        Start a new repository analysis.

        1. Creates an Analysis record in the database (STARTED status)
        2. Starts the LangGraph workflow in a background task
        3. Returns the analysis ID immediately (202 Accepted)

        Args:
            repository_url: Full GitHub URL
            owner: Repository owner
            repo: Repository name

        Returns:
            Dict with analysis_id, status, repository_name, created_at
        """
        analysis_id = str(uuid.uuid4())
        thread_id = str(uuid.uuid4())  # LangGraph checkpoint thread
        repository_name = f"{owner}/{repo}"

        async with get_db_session() as session:
            repo_obj = AnalysisRepository(session)
            analysis = await repo_obj.create(
                analysis_id=analysis_id,
                repository_url=repository_url,
                repository_name=repository_name,
                owner=owner,
                repo=repo,
                langgraph_thread_id=thread_id,
            )
            created_at = analysis.created_at.isoformat()

        # Start the LangGraph workflow as a background task
        # asyncio.create_task ensures it runs without blocking the response
        asyncio.create_task(
            self._run_workflow(
                analysis_id=analysis_id,
                thread_id=thread_id,
                repository_url=repository_url,
                owner=owner,
                repo=repo,
            ),
            name=f"analysis-{analysis_id}",
        )

        logger.info(
            "analysis_started",
            analysis_id=analysis_id,
            repository=repository_name,
            thread_id=thread_id,
        )

        return {
            "analysis_id": analysis_id,
            "status": "STARTED",
            "repository_name": repository_name,
            "created_at": created_at,
        }

    async def get_status(self, analysis_id: str) -> Optional[dict[str, Any]]:
        """
        Return current status of an analysis.

        Checks Redis cache first, falls back to database.
        """
        # Try cache first
        if self._cache:
            cached = await self._cache.get(analysis_status_key(analysis_id))
            if cached:
                return cached

        async with get_db_session() as session:
            analysis = await AnalysisRepository(session).get_by_id(analysis_id)

        if not analysis:
            return None

        status_data = {
            "analysis_id": analysis.id,
            "status": analysis.status,
            "repository_name": analysis.repository_name,
            "repository_url": analysis.repository_url,
            "current_node": analysis.current_node,
            "progress": analysis.progress,
            "revision_count": analysis.revision_count,
            "errors": analysis.errors or [],
            "warnings": analysis.warnings or [],
            "created_at": analysis.created_at.isoformat(),
            "updated_at": analysis.updated_at.isoformat(),
            "completed_at": analysis.completed_at.isoformat() if analysis.completed_at else None,
        }

        # Cache for short TTL to reduce DB pressure on status polling
        if self._cache:
            await self._cache.set(
                analysis_status_key(analysis_id),
                status_data,
                ttl=TTL_ANALYSIS_STATUS,
            )

        return status_data

    async def get_report(self, analysis_id: str) -> Optional[dict[str, Any]]:
        """
        Return the final report if analysis is completed.

        Returns None if the analysis doesn't exist.
        Returns the report dict if completed.
        Raises ValueError if not yet completed.
        """
        async with get_db_session() as session:
            analysis = await AnalysisRepository(session).get_by_id(analysis_id)
            if not analysis:
                return None

            if analysis.status not in ("COMPLETED", "AWAITING_APPROVAL"):
                raise ValueError(
                    f"Report not yet available. Current status: {analysis.status}"
                )

            report = await ReportRepository(session).get_by_analysis_id(analysis_id)

        if not report:
            raise ValueError("Report record not found despite completed status.")

        return {
            "analysis_id": analysis_id,
            "repository_name": analysis.repository_name,
            "status": analysis.status,
            "report_markdown": report.content,
            "report_metadata": report.report_metadata or {},
            "generated_at": report.created_at.isoformat(),
        }

    async def process_approval(
        self,
        analysis_id: str,
        action: str,
        feedback_text: Optional[str] = None,
        revision_instructions: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Process a human approval decision.

        Actions:
          APPROVE          → mark COMPLETED, finalize
          REJECT           → mark REJECTED, no revision
          REQUEST_REVISION → re-queue improvement planner with feedback

        Args:
            analysis_id: Analysis to act on
            action: APPROVE | REJECT | REQUEST_REVISION
            feedback_text: Human reviewer comments
            revision_instructions: Specific revision instructions for REVISION

        Returns:
            Updated status dict

        Raises:
            ValueError: If analysis is not in AWAITING_APPROVAL state
        """
        async with get_db_session() as session:
            analysis_repo = AnalysisRepository(session)
            feedback_repo = FeedbackRepository(session)

            analysis = await analysis_repo.get_by_id(analysis_id)
            if not analysis:
                return None

            if analysis.status != "AWAITING_APPROVAL":
                raise ValueError(
                    f"Analysis is not awaiting approval. Current status: {analysis.status}"
                )

            # Record feedback
            revision_number = analysis.revision_count
            await feedback_repo.create(
                analysis_id=analysis_id,
                action=action,
                feedback_text=feedback_text,
                revision_instructions=revision_instructions,
                revision_number=revision_number,
            )

            # Update analysis status
            if action == "APPROVE":
                new_status = "COMPLETED"
            elif action == "REJECT":
                new_status = "REJECTED"
            elif action == "REQUEST_REVISION":
                new_status = "REVISION_REQUESTED"
            else:
                raise ValueError(f"Unknown approval action: {action}")

            await analysis_repo.update_status(
                analysis_id=analysis_id,
                status=new_status,
                progress=f"Human review: {action}",
            )

            thread_id = analysis.langgraph_thread_id

        # Invalidate status cache
        if self._cache:
            await self._cache.delete(analysis_status_key(analysis_id))

        logger.info(
            "analysis_approval_processed",
            analysis_id=analysis_id,
            action=action,
            new_status=new_status,
        )

        # For revision requests, resume the LangGraph workflow
        if action == "REQUEST_REVISION" and thread_id:
            asyncio.create_task(
                self._resume_workflow(
                    analysis_id=analysis_id,
                    thread_id=thread_id,
                    action=action,
                    feedback_text=feedback_text,
                    revision_instructions=revision_instructions,
                ),
                name=f"revision-{analysis_id}",
            )

        return {
            "analysis_id": analysis_id,
            "action": action,
            "new_status": new_status,
        }

    # ── Private workflow methods ───────────────────────────────────────────────

    async def _run_workflow(
        self,
        analysis_id: str,
        thread_id: str,
        repository_url: str,
        owner: str,
        repo: str,
    ) -> None:
        """
        Run the LangGraph workflow to completion in the background.

        Updates the database at each major transition.
        """
        from app.mcp.client import MCPClient
        from app.services.cache_service import get_cache_service
        from app.services.llm.gemini_provider import get_llm_provider

        try:
            # Build workflow with real providers
            cache = await get_cache_service()
            mcp = MCPClient(cache_service=cache)
            llm = get_llm_provider()
            workflow = build_workflow(
                llm_provider=llm,
                mcp_client=mcp,
            )

            config = {"configurable": {"thread_id": thread_id}}

            # Build initial state
            state = initial_state(
                analysis_id=analysis_id,
                repository_url=repository_url,
                owner=owner,
                repo=repo,
            )

            # Update DB: analysis is now running
            async with get_db_session() as session:
                await AnalysisRepository(session).update_status(
                    analysis_id=analysis_id,
                    status="RUNNING",
                    current_node="repository_discovery",
                    progress="Discovering repository structure…",
                )

            # Stream events from the workflow
            async for event in workflow.astream(state, config=config):
                node_name = next(iter(event.keys()), "unknown")
                node_output = event.get(node_name, {})

                logger.info(
                    "workflow_node_completed",
                    analysis_id=analysis_id,
                    node=node_name,
                )

                # Determine new status for DB update
                if node_name == "human_approval":
                    # Workflow paused for human review
                    async with get_db_session() as session:
                        analysis_repo = AnalysisRepository(session)
                        report_repo = ReportRepository(session)

                        # Persist the final report
                        final_state = node_output
                        if final_state.get("final_report"):
                            await report_repo.create_or_update(
                                analysis_id=analysis_id,
                                content=final_state["final_report"],
                                report_metadata=final_state.get("report_metadata"),
                            )

                        await analysis_repo.update_status(
                            analysis_id=analysis_id,
                            status="AWAITING_APPROVAL",
                            current_node="human_approval",
                            progress="Analysis complete. Awaiting human approval.",
                        )
                    break  # Workflow is interrupted — stop streaming

                # Persist partial state after each node
                async with get_db_session() as session:
                    await AnalysisRepository(session).update_analysis_outputs(
                        analysis_id=analysis_id,
                        state=node_output,
                    )

        except Exception as exc:
            logger.error(
                "workflow_failed",
                analysis_id=analysis_id,
                error=str(exc),
                exc_info=True,
            )
            async with get_db_session() as session:
                await AnalysisRepository(session).update_status(
                    analysis_id=analysis_id,
                    status="FAILED",
                    current_node="error",
                    error_message=str(exc),
                    progress=f"Analysis failed: {str(exc)[:200]}",
                )

    async def _resume_workflow(
        self,
        analysis_id: str,
        thread_id: str,
        action: str,
        feedback_text: Optional[str],
        revision_instructions: Optional[str],
    ) -> None:
        """
        Resume a LangGraph workflow after a human revision request.

        Injects the feedback into the checkpointed state and re-runs.
        """
        from app.mcp.client import MCPClient
        from app.services.cache_service import get_cache_service
        from app.services.llm.gemini_provider import get_llm_provider

        try:
            cache = await get_cache_service()
            mcp = MCPClient(cache_service=cache)
            llm = get_llm_provider()
            workflow = build_workflow(llm_provider=llm, mcp_client=mcp)

            config = {"configurable": {"thread_id": thread_id}}

            # Inject feedback into the state update for the resumed run
            feedback: ApprovalFeedback = {
                "action": action,
                "feedback_text": feedback_text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "revision_instructions": revision_instructions,
            }

            # Update status and increment revision count
            async with get_db_session() as session:
                analysis = await AnalysisRepository(session).get_by_id(analysis_id)
                revision_count = (analysis.revision_count or 0) + 1
                await AnalysisRepository(session).update_status(
                    analysis_id=analysis_id,
                    status="RUNNING",
                    current_node="improvement_planner",
                    progress=f"Revision #{revision_count} in progress…",
                )

            # Resume workflow — LangGraph resumes from the last checkpoint
            async for event in workflow.astream(
                {
                    "approval_status": action,
                    "approval_feedback": feedback,
                    "revision_count": revision_count,
                },
                config=config,
            ):
                node_name = next(iter(event.keys()), "unknown")
                logger.info(
                    "revision_node_completed",
                    analysis_id=analysis_id,
                    node=node_name,
                    revision=revision_count,
                )

                if node_name == "human_approval":
                    async with get_db_session() as session:
                        node_output = event.get(node_name, {})
                        if node_output.get("final_report"):
                            await ReportRepository(session).create_or_update(
                                analysis_id=analysis_id,
                                content=node_output["final_report"],
                                report_metadata=node_output.get("report_metadata"),
                            )
                        await AnalysisRepository(session).update_status(
                            analysis_id=analysis_id,
                            status="AWAITING_APPROVAL",
                            current_node="human_approval",
                            progress=f"Revision #{revision_count} complete. Awaiting approval.",
                        )
                    break

        except Exception as exc:
            logger.error(
                "revision_workflow_failed",
                analysis_id=analysis_id,
                error=str(exc),
                exc_info=True,
            )
            async with get_db_session() as session:
                await AnalysisRepository(session).update_status(
                    analysis_id=analysis_id,
                    status="FAILED",
                    error_message=str(exc),
                )
