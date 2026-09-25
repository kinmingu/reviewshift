"""Add review embeddings for semantic retrieval (pgvector, bge-m3 1024 dims).

Revision ID: 0005_review_embeddings
Revises: 0004_human_eval_metrics
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0005_review_embeddings"
down_revision: str | None = "0004_human_eval_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_embeddings",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("review_id", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("model_digest", sa.String(length=80), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id", "model", name="uq_review_embeddings_review_model"),
    )
    op.create_index(
        "ix_review_embeddings_review_id", "review_embeddings", ["review_id"], unique=False
    )
    # 코사인 거리 근사 최근접 검색 인덱스(상품·기간 필터 후 정렬에 사용)
    op.create_index(
        "ix_review_embeddings_hnsw",
        "review_embeddings",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_review_embeddings_hnsw", table_name="review_embeddings")
    op.drop_index("ix_review_embeddings_review_id", table_name="review_embeddings")
    op.drop_table("review_embeddings")
