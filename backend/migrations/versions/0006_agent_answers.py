"""Store pre-generated FAQ answers and cached chatbot answers.

Revision ID: 0006_agent_answers
Revises: 0005_review_embeddings
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_agent_answers"
down_revision: str | None = "0005_review_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_answers",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("product_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("faq_key", sa.String(length=40), nullable=True),
        sa.Column("question_key", sa.String(length=600), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("citations_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tool_calls_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("generation_attempts", sa.Integer(), nullable=False),
        sa.Column("is_provisional", sa.Boolean(), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("analysis_version", sa.String(length=64), nullable=False),
        sa.Column("analyzed_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('faq', 'cache')", name="ck_agent_answers_kind"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id", "question_key", "prompt_version", name="uq_agent_answers_question"
        ),
    )
    op.create_index(
        "ix_agent_answers_product_id", "agent_answers", ["product_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_agent_answers_product_id", table_name="agent_answers")
    op.drop_table("agent_answers")
