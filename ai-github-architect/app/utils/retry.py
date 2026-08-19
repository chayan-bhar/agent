"""
Exponential backoff retry decorator using tenacity.

Usage:
    from app.utils.retry import with_retry, with_github_retry

    @with_retry(max_attempts=3)
    async def call_api():
        ...

    @with_github_retry
    async def fetch_file():
        ...
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random_exponential,
)

from app.utils.logging import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ── Retryable exception sets ──────────────────────────────────────────────────

# GitHub API exceptions that are worth retrying
_GITHUB_RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
)

# LLM call exceptions worth retrying (provider-agnostic base classes)
_LLM_RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
    ValueError,  # Structured output parsing failures — retry with correction
)


# ── Generic retry decorator ───────────────────────────────────────────────────


def with_retry(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 30.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """
    Decorator that retries an async function with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts (including the first).
        min_wait: Minimum wait between retries in seconds.
        max_wait: Maximum wait between retries in seconds.
        exceptions: Only retry on these exception types.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            async for attempt_ctx in AsyncRetrying(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
                retry=retry_if_exception_type(exceptions),
                reraise=True,
            ):
                with attempt_ctx:
                    attempt += 1
                    try:
                        return await func(*args, **kwargs)
                    except exceptions as exc:
                        if attempt < max_attempts:
                            logger.warning(
                                "retry_scheduled",
                                func=func.__qualname__,
                                attempt=attempt,
                                max_attempts=max_attempts,
                                error=str(exc),
                            )
                        raise

        return wrapper  # type: ignore[return-value]

    return decorator


# ── Pre-configured retry decorators ──────────────────────────────────────────


def with_github_retry(func: F) -> F:
    """Retry decorator pre-configured for GitHub API calls (3 attempts, jittered)."""

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        attempt = 0
        async for attempt_ctx in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_random_exponential(multiplier=1, min=2, max=20),
            retry=retry_if_exception_type(_GITHUB_RETRYABLE_EXCEPTIONS),
            reraise=True,
        ):
            with attempt_ctx:
                attempt += 1
                try:
                    return await func(*args, **kwargs)
                except _GITHUB_RETRYABLE_EXCEPTIONS as exc:
                    if attempt < 3:
                        logger.warning(
                            "github_api_retry",
                            func=func.__qualname__,
                            attempt=attempt,
                            error=str(exc),
                        )
                    raise

    return wrapper  # type: ignore[return-value]


def with_llm_retry(func: F) -> F:
    """Retry decorator pre-configured for LLM calls (3 attempts, longer backoff)."""

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        attempt = 0
        async for attempt_ctx in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=2, min=5, max=60),
            retry=retry_if_exception_type(_LLM_RETRYABLE_EXCEPTIONS),
            reraise=True,
        ):
            with attempt_ctx:
                attempt += 1
                try:
                    return await func(*args, **kwargs)
                except _LLM_RETRYABLE_EXCEPTIONS as exc:
                    if attempt < 3:
                        logger.warning(
                            "llm_retry",
                            func=func.__qualname__,
                            attempt=attempt,
                            error=str(exc),
                        )
                    raise

    return wrapper  # type: ignore[return-value]
