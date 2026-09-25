"""Add resumable, versioned review analysis processing records.

Revision ID: 0003_review_analysis_runs
Revises: 0002_review_translation_cache
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_review_analysis_runs"
down_revision: str | None = "0002_review_translation_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column("source_mode", sa.String(length=16), server_default="fixture", nullable=False),
    )
    op.add_column(
        "analysis_runs",
        sa.Column("is_active", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "analysis_runs",
        sa.Column("target_review_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "analysis_runs", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE analysis_runs SET is_active = true WHERE id = 'fixture-analysis-v1'"
    )
    op.create_index(
        "uq_analysis_runs_active_source",
        "analysis_runs",
        ["source_mode"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "review_analysis_results",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("review_id", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("input_chars", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("last_error_type", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "error_history",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_review_analysis_status",
        ),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "review_id", name="uq_review_analysis_run_review"),
    )
    op.create_index(
        "ix_review_analysis_run_status",
        "review_analysis_results",
        ["run_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_review_analysis_run_status", table_name="review_analysis_results")
    op.drop_table("review_analysis_results")
    op.drop_index("uq_analysis_runs_active_source", table_name="analysis_runs")
    op.drop_column("analysis_runs", "completed_at")
    op.drop_column("analysis_runs", "config_json")
    op.drop_column("analysis_runs", "target_review_count")
    op.drop_column("analysis_runs", "is_active")
    op.drop_column("analysis_runs", "source_mode")
