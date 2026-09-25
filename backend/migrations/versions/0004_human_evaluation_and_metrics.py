"""Add human evaluation workflow and detailed model timing metrics.

Revision ID: 0004_human_eval_metrics
Revises: 0003_review_analysis_runs
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_human_eval_metrics"
down_revision: str | None = "0003_review_analysis_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "review_analysis_results",
        sa.Column(
            "model_metrics_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "review_analysis_results",
        sa.Column("db_write_ms", sa.Integer(), nullable=True),
    )
    op.create_table(
        "human_review_evaluations",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("dataset_id", sa.String(length=80), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("split", sa.String(length=40), nullable=False),
        sa.Column("review_id", sa.String(length=64), nullable=False),
        sa.Column(
            "prompt_tuning_used", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("reviewer", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "is_normal_empty", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "gold_labels_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed')", name="ck_human_evaluation_status"
        ),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dataset_id", "position", name="uq_human_evaluation_dataset_position"
        ),
        sa.UniqueConstraint(
            "dataset_id", "review_id", name="uq_human_evaluation_dataset_review"
        ),
    )
    op.create_index(
        "ix_human_evaluation_dataset_status",
        "human_review_evaluations",
        ["dataset_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_human_evaluation_dataset_status",
        table_name="human_review_evaluations",
    )
    op.drop_table("human_review_evaluations")
    op.drop_column("review_analysis_results", "db_write_ms")
    op.drop_column("review_analysis_results", "model_metrics_json")
