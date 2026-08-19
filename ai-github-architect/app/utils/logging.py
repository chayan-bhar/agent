"""
Structured logging setup using structlog.

Usage:
    from app.utils.logging import get_logger
    logger = get_logger(__name__)
    logger.info("analysis_started", analysis_id=analysis_id, repo=repo_url)
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.config.settings import LogLevel, get_settings


def _add_app_context(
    logger: Any, method_name: str, event_dict: EventDict
) -> EventDict:
    """Inject constant app-level context into every log record."""
    event_dict.setdefault("app", "ai-github-architect")
    return event_dict


def _drop_color_message_key(
    logger: Any, method_name: str, event_dict: EventDict
) -> EventDict:
    """Remove uvicorn's color_message key to keep logs clean."""
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging() -> None:
    """
    Configure structlog and stdlib logging.

    Call this once at application startup before any other imports that log.
    In development: pretty console output with colors.
    In production: JSON output for log aggregators (Datadog, GCP, etc.).
    """
    settings = get_settings()
    log_level_str: str = settings.app_log_level.value
    log_level: int = getattr(logging, log_level_str, logging.INFO)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        _add_app_context,
        _drop_color_message_key,
    ]

    if settings.is_development:
        # Human-readable colored output in development
        processors: list[Processor] = shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ]
        renderer: Processor = structlog.dev.ConsoleRenderer(colors=True)
    else:
        # JSON output in staging / production
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ]
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Wire stdlib logging through structlog's ProcessorFormatter
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)
    # Quiet noisy third-party loggers
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.BoundLogger:
    """Return a bound structlog logger for the given module name."""
    return structlog.get_logger(name)
