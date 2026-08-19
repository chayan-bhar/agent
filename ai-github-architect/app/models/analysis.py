"""
SQLAlchemy async ORM models.

Tables:
  analyses    — One row per analysis job
  reports     — Final generated Markdown reports
  feedback    — Human approval feedback records

Design:
  - All timestamps in UTC
  - UUIDs as primary keys (string representation for portability)
  - JSON columns for flexible structured data (analysis outputs, metadata)
  - No secrets stored in the database
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


# ── Base ──────────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


# ── Analysis ──────────────────────────────────────────────────────────────────


class Analysis(Base):
    """
    Represents a single repository analysis job.

    Tracks the full lifecycle from STARTED → RUNNING → AWAITING_APPROVAL
    → APPROVED/REJECTED → COMPLETED/FAILED.
    """

    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_uuid
    )
    repository_url: Mapped[str] = mapped_column(String(500), nullable=False)
    repository_name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner: Mapped[str] = mapped_column(String(100), nullable=False)
    repo: Mapped[str] = mapped_column(String(100), nullable=False)

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="STARTED", index=True
    )
    current_node: Mapped[str | None] = mapped_column(String(50), nullable=True)
    progress: Mapped[str | None] = mapped_column(String(500), nullable=True)
    revision_count: Mapped[int] = mapped_column(Integer, default=0)

    # Structured analysis outputs (PostgreSQL JSONB for indexability)
    repository_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    repository_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    architecture_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    security_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    performance_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    code_quality_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    improvement_recommendations: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Error tracking
    errors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # LangGraph thread ID for checkpoint lookup
    langgraph_thread_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    report: Mapped["Report | None"] = relationship(
        "Report", back_populates="analysis", uselist=False, cascade="all, delete-orphan"
    )
    feedback_records: Mapped[list["Feedback"]] = relationship(
        "Feedback", back_populates="analysis", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_analyses_status_created", "status", "created_at"),
        Index("ix_analyses_repository_name", "repository_name"),
    )

    def __repr__(self) -> str:
        return f"<Analysis id={self.id} repo={self.repository_name} status={self.status}>"


# ── Report ────────────────────────────────────────────────────────────────────


class Report(Base):
    """
    Final generated Markdown report for a completed analysis.

    Stored separately from Analysis to keep the analyses table lean.
    """

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_uuid
    )
    analysis_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)  # Full Markdown
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    report_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    analysis: Mapped["Analysis"] = relationship("Analysis", back_populates="report")

    def __repr__(self) -> str:
        return f"<Report id={self.id} analysis_id={self.analysis_id}>"


# ── Feedback ──────────────────────────────────────────────────────────────────


class Feedback(Base):
    """
    Human approval feedback record.

    One analysis can have multiple feedback records (one per revision cycle).
    """

    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_uuid
    )
    analysis_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    action: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # APPROVE | REJECT | REQUEST_REVISION
    feedback_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision_number: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    analysis: Mapped["Analysis"] = relationship("Analysis", back_populates="feedback_records")

    def __repr__(self) -> str:
        return f"<Feedback id={self.id} action={self.action} analysis={self.analysis_id}>"
