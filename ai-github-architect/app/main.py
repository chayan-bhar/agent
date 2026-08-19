"""
FastAPI application factory.

This module creates and configures the FastAPI app instance.
Import `app` from here for use with uvicorn.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config.settings import get_settings
from app.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown events for the application."""
    settings = get_settings()
    logger.info(
        "application_starting",
        env=settings.app_env.value,
        version=application.version,
        llm_provider=settings.llm_provider.value,
        gemini_model=settings.gemini_model,
    )

    # ── Startup ───────────────────────────────────────────────────────────────
    # Future: initialize DB connection pool, Redis pool, MCP client registry
    yield
    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("application_shutdown")


# ── App factory ───────────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging()
    settings = get_settings()

    application = FastAPI(
        title="AI GitHub Repository Architect",
        description=(
            "An AI agent that analyzes GitHub repositories and produces detailed "
            "technical architecture reports covering structure, security, performance, "
            "and improvement opportunities."
        ),
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── CORS ─────────────────────────────────────────────────────────────────
    # In production, replace "*" with allowed origins from config
    allowed_origins = ["*"] if settings.is_development else []
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request timing middleware ─────────────────────────────────────────────
    @application.middleware("http")
    async def add_request_timing(request: Request, call_next):  # type: ignore[no-untyped-def]
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Process-Time-Ms"] = str(duration_ms)
        return response

    # ── Global exception handler ──────────────────────────────────────────────
    @application.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            method=request.method,
            url=str(request.url),
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "An unexpected error occurred.",
                "type": type(exc).__name__,
            },
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    application.include_router(api_router)

    return application


# Module-level app instance used by uvicorn
app = create_app()


def main() -> None:
    """Entrypoint for the `architect` CLI command."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.is_development,
        log_level=settings.app_log_level.value.lower(),
    )


if __name__ == "__main__":
    main()
