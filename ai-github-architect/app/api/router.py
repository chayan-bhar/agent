"""
Top-level API router.

All versioned routers are registered here. This keeps app/main.py clean
and makes it easy to add /api/v2 without touching existing routes.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.analysis import router as analysis_router
from app.api.v1.health import router as health_router

api_router = APIRouter(prefix="/api")

api_router.include_router(health_router, tags=["Health"])
api_router.include_router(analysis_router, prefix="/v1", tags=["Analysis"])
