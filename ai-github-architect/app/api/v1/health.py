"""
Health check endpoint.

GET /api/health  — lightweight liveness probe used by Docker healthchecks,
                   load balancers, and Kubernetes probes.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.config.settings import get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str
    environment: str


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Lightweight liveness probe. Returns 200 when the service is running.",
)
async def health_check() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc).isoformat(),
        version="0.1.0",
        environment=settings.app_env.value,
    )
