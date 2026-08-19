"""Initial PostgreSQL schema for analyses, reports, and feedback

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-08-19 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Table: analyses ───────────────────────────────────────────────────────
    op.create_table(
        'analyses',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('repository_url', sa.String(length=500), nullable=False),
        sa.Column('repository_name', sa.String(length=200), nullable=False),
        sa.Column('owner', sa.String(length=100), nullable=False),
        sa.Column('repo', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('current_node', sa.String(length=50), nullable=True),
        sa.Column('progress', sa.String(length=500), nullable=True),
        sa.Column('revision_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('repository_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('repository_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('architecture_analysis', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('security_analysis', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('performance_analysis', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('code_quality_analysis', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('improvement_recommendations', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('errors', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('warnings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('langgraph_thread_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('langgraph_thread_id')
    )
    op.create_index('ix_analyses_repository_name', 'analyses', ['repository_name'], unique=False)
    op.create_index('ix_analyses_status', 'analyses', ['status'], unique=False)
    op.create_index('ix_analyses_status_created', 'analyses', ['status', 'created_at'], unique=False)

    # ── Table: reports ────────────────────────────────────────────────────────
    op.create_table(
        'reports',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('analysis_id', sa.String(length=36), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('word_count', sa.Integer(), nullable=True),
        sa.Column('report_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('analysis_id')
    )
    op.create_index('ix_reports_analysis_id', 'reports', ['analysis_id'], unique=False)

    # ── Table: feedback ───────────────────────────────────────────────────────
    op.create_table(
        'feedback',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('analysis_id', sa.String(length=36), nullable=False),
        sa.Column('action', sa.String(length=30), nullable=False),
        sa.Column('feedback_text', sa.Text(), nullable=True),
        sa.Column('revision_instructions', sa.Text(), nullable=True),
        sa.Column('revision_number', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_feedback_analysis_id', 'feedback', ['analysis_id'], unique=False)


def downgrade() -> None:
    op.drop_table('feedback')
    op.drop_table('reports')
    op.drop_table('analyses')
