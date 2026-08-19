"""
Database engine and session management.

Provides:
  - Async SQLAlchemy engine factory
  - AsyncSession dependency for FastAPI
  - Connection pool configuration
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Module-level engine & session factory (created once at startup)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the async SQLAlchemy engine, creating it on first call."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.is_development,        # Log SQL in dev
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,                  # Detect stale connections
            pool_recycle=3600,                   # Recycle connections every hour
        )
        logger.info("database_engine_created", url=_mask_url(settings.database_url))
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the async session factory, creating it on first call."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _session_factory


@asynccontextmanager
async def get_db_session() -> AsyncIterator[AsyncSession]:
    """
    Async context manager yielding a database session.

    Commits on success, rolls back on exception, always closes.

    Usage:
        async with get_db_session() as session:
            result = await session.execute(...)
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def dispose_engine() -> None:
    """Dispose the engine (call during application shutdown)."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
        logger.info("database_engine_disposed")


def _mask_url(url: str) -> str:
    """Mask password in database URL for safe logging."""
    try:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(url)
        if parsed.password:
            masked = parsed._replace(
                netloc=parsed.netloc.replace(parsed.password, "****")
            )
            return urlunparse(masked)
    except Exception:
        pass
    return url
