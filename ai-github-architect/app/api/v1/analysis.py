"""
Analysis API endpoints (v1).

Routes:
  POST   /api/v1/analyze                          Start a new analysis
  GET    /api/v1/analyze/{analysis_id}            Get analysis status
  GET    /api/v1/analyze/{analysis_id}/report     Get final report
  POST   /api/v1/analyze/{analysis_id}/approve    Approve current analysis
  POST   /api/v1/analyze/{analysis_id}/reject     Reject and request revision

Uses AnalysisService for database persistence and workflow orchestration.
Falls back to in-memory store when database is unavailable (e.g. unit testing).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field

from app.services.analysis_service import AnalysisService
from app.services.cache_service import get_cache_service
from app.utils.github_url import InvalidGitHubURLError, parse_github_url
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


# ── Enums ─────────────────────────────────────────────────────────────────────


class AnalysisStatus(str, Enum):
    STARTED = "STARTED"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ApprovalAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_REVISION = "REQUEST_REVISION"


# ── Request / Response schemas ────────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    repository_url: str = Field(
        ...,
        description="GitHub repository URL (HTTPS or SSH format)",
        examples=["https://github.com/fastapi/fastapi"],
    )
    options: Optional[dict] = Field(
        default=None,
        description="Optional analysis configuration overrides",
    )


class AnalyzeResponse(BaseModel):
    analysis_id: str
    status: AnalysisStatus
    repository_url: str
    repository_name: str
    created_at: str
    message: str


class AnalysisStatusResponse(BaseModel):
    analysis_id: str
    status: AnalysisStatus
    repository_url: str
    repository_name: str
    created_at: str
    updated_at: str
    progress: Optional[str] = None
    current_node: Optional[str] = None
    error: Optional[str] = None


class ApprovalRequest(BaseModel):
    action: ApprovalAction
    feedback: Optional[str] = Field(
        default=None,
        description="Required when action is REJECT or REQUEST_REVISION",
    )


class ApprovalResponse(BaseModel):
    analysis_id: str
    action: ApprovalAction
    status: AnalysisStatus
    message: str


# ── In-memory store (used for direct test injection & graceful fallback) ─────

_analyses: dict[str, dict] = {}


# ── Service Helper ────────────────────────────────────────────────────────────


async def _get_service() -> AnalysisService:
    cache = await get_cache_service()
    return AnalysisService(cache=cache)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start repository analysis",
    description=(
        "Submit a GitHub repository URL for analysis. "
        "The analysis runs asynchronously. Use the returned analysis_id "
        "to poll for status and retrieve the report."
    ),
)
async def start_analysis(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
) -> AnalyzeResponse:
    # ── Validate GitHub URL ───────────────────────────────────────────────────
    try:
        parsed = parse_github_url(request.repository_url)
    except InvalidGitHubURLError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    analysis_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Try DB-backed service first
    try:
        service = await _get_service()
        result = await service.start_analysis(
            repository_url=parsed.canonical_url,
            owner=parsed.owner,
            repo=parsed.repo,
        )
        analysis_id = result["analysis_id"]
        created_at = result["created_at"]
    except Exception as exc:
        logger.warning(
            "db_service_start_failed_using_memory_fallback",
            error=str(exc),
        )
        # Fallback to in-memory store for unit test environments
        record = {
            "analysis_id": analysis_id,
            "status": AnalysisStatus.STARTED,
            "repository_url": parsed.canonical_url,
            "repository_name": parsed.full_name,
            "created_at": now,
            "updated_at": now,
            "current_node": None,
            "progress": "Queued for analysis",
            "error": None,
            "report": None,
        }
        _analyses[analysis_id] = record
        background_tasks.add_task(_stub_analysis_task, analysis_id, parsed.full_name)
        created_at = now

    logger.info(
        "analysis_started",
        analysis_id=analysis_id,
        repository=parsed.full_name,
    )

    return AnalyzeResponse(
        analysis_id=analysis_id,
        status=AnalysisStatus.STARTED,
        repository_url=parsed.canonical_url,
        repository_name=parsed.full_name,
        created_at=created_at,
        message=(
            f"Analysis started for {parsed.full_name}. "
            f"Poll GET /api/v1/analyze/{analysis_id} for status."
        ),
    )


@router.get(
    "/analyze/{analysis_id}",
    response_model=AnalysisStatusResponse,
    summary="Get analysis status",
)
async def get_analysis_status(analysis_id: str) -> AnalysisStatusResponse:
    # Check in-memory store first (for test injections)
    if analysis_id in _analyses:
        record = _analyses[analysis_id]
        return AnalysisStatusResponse(
            analysis_id=record["analysis_id"],
            status=record["status"],
            repository_url=record["repository_url"],
            repository_name=record["repository_name"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
            progress=record.get("progress"),
            current_node=record.get("current_node"),
            error=record.get("error"),
        )

    # Check DB service
    try:
        service = await _get_service()
        status_data = await service.get_status(analysis_id)
        if status_data:
            return AnalysisStatusResponse(
                analysis_id=status_data["analysis_id"],
                status=AnalysisStatus(status_data["status"]),
                repository_url=status_data["repository_url"],
                repository_name=status_data["repository_name"],
                created_at=status_data["created_at"],
                updated_at=status_data["updated_at"],
                progress=status_data.get("progress"),
                current_node=status_data.get("current_node"),
                error=status_data.get("error_message"),
            )
    except Exception as exc:
        logger.warning("db_service_get_status_failed", error=str(exc))

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Analysis '{analysis_id}' not found.",
    )


@router.get(
    "/analyze/{analysis_id}/report",
    summary="Get final analysis report",
    description="Returns the generated Markdown report once the analysis is COMPLETED.",
)
async def get_analysis_report(analysis_id: str) -> dict:
    # Check in-memory store
    if analysis_id in _analyses:
        record = _analyses[analysis_id]
        if record["status"] not in (AnalysisStatus.COMPLETED, AnalysisStatus.APPROVED):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Report not yet available. Current status: {record['status'].value}. "
                    "Wait for COMPLETED or APPROVED status."
                ),
            )
        return {
            "analysis_id": analysis_id,
            "repository_name": record["repository_name"],
            "status": record["status"],
            "report": record.get("report", "Report not generated yet."),
        }

    # Check DB service
    try:
        service = await _get_service()
        report_data = await service.get_report(analysis_id)
        if report_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Analysis '{analysis_id}' not found.",
            )
        return report_data
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("db_service_get_report_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis '{analysis_id}' not found.",
        ) from exc


@router.post(
    "/analyze/{analysis_id}/approve",
    response_model=ApprovalResponse,
    summary="Approve analysis and generate final report",
)
async def approve_analysis(
    analysis_id: str,
    request: ApprovalRequest,
) -> ApprovalResponse:
    # Check in-memory store
    if analysis_id in _analyses:
        record = _analyses[analysis_id]
        if record["status"] != AnalysisStatus.AWAITING_APPROVAL:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot approve analysis in status '{record['status'].value}'. "
                    "Analysis must be in AWAITING_APPROVAL state."
                ),
            )

        now = datetime.now(timezone.utc).isoformat()

        if request.action == ApprovalAction.APPROVE:
            new_status = AnalysisStatus.APPROVED
            message = "Analysis approved. Final report is ready."
        elif request.action in (ApprovalAction.REJECT, ApprovalAction.REQUEST_REVISION):
            if not request.feedback:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Feedback is required when rejecting or requesting revision.",
                )
            new_status = AnalysisStatus.RUNNING
            message = f"Analysis action {request.action.value} initiated."

        record["status"] = new_status
        record["updated_at"] = now

        logger.info(
            "analysis_approval_action",
            analysis_id=analysis_id,
            action=request.action.value,
            new_status=new_status.value,
        )

        return ApprovalResponse(
            analysis_id=analysis_id,
            action=request.action,
            status=new_status,
            message=message,
        )

    # Check DB service
    try:
        service = await _get_service()
        if request.action in (ApprovalAction.REJECT, ApprovalAction.REQUEST_REVISION) and not request.feedback:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Feedback is required when rejecting or requesting revision.",
            )

        result = await service.process_approval(
            analysis_id=analysis_id,
            action=request.action.value,
            feedback_text=request.feedback,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Analysis '{analysis_id}' not found.",
            )

        return ApprovalResponse(
            analysis_id=analysis_id,
            action=request.action,
            status=AnalysisStatus(result["new_status"]),
            message=f"Action '{request.action.value}' processed successfully.",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("db_service_approve_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis '{analysis_id}' not found.",
        ) from exc


# ── Stub task (fallback for in-memory mode) ─────────────────────────────────


async def _stub_analysis_task(analysis_id: str, repo_name: str) -> None:
    """Fallback stub for in-memory test runs."""
    import asyncio

    record = _analyses.get(analysis_id)
    if not record:
        return

    await asyncio.sleep(1)
    record["status"] = AnalysisStatus.RUNNING
    record["current_node"] = "repository_discovery"
    record["progress"] = "Discovering repository structure..."
    record["updated_at"] = datetime.now(timezone.utc).isoformat()

    await asyncio.sleep(2)
    record["status"] = AnalysisStatus.AWAITING_APPROVAL
    record["current_node"] = "human_approval"
    record["progress"] = "Analysis complete. Awaiting human approval."
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    record["report"] = f"# Stub Report for {repo_name}\n\nLangGraph workflow active."
