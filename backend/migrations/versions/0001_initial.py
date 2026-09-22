"""Create stage 1 catalog and review tables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "products",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_mode", sa.String(length=16), nullable=False),
        sa.Column("parent_asin", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("parent_asin"),
    )
    op.create_index("ix_products_category", "products", ["category"], unique=False)
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("label_schema_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "reviews",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("product_id", sa.String(length=64), nullable=False),
        sa.Column("source_record_key", sa.String(length=160), nullable=False),
        sa.Column("source_mode", sa.String(length=16), nullable=False),
        sa.Column("asin", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_reviews_rating"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_record_key"),
    )
    op.create_index(
        "ix_reviews_product_reviewed_at",
        "reviews",
        ["product_id", "reviewed_at"],
        unique=False,
    )
    op.create_table(
        "review_labels",
        sa.Column("id", sa.String(length=96), nullable=False),
        sa.Column("review_id", sa.String(length=64), nullable=False),
        sa.Column("aspect", sa.String(length=80), nullable=False),
        sa.Column("detail_label", sa.String(length=120), nullable=False),
        sa.Column("polarity", sa.String(length=16), nullable=False),
        sa.Column("evidence_span", sa.Text(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "review_id",
            "aspect",
            "detail_label",
            "polarity",
            "evidence_span",
            "run_id",
            name="uq_review_labels_evidence",
        ),
    )
    op.create_index(
        "ix_review_labels_lookup",
        "review_labels",
        ["aspect", "polarity", "review_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_review_labels_lookup", table_name="review_labels")
    op.drop_table("review_labels")
    op.drop_index("ix_reviews_product_reviewed_at", table_name="reviews")
    op.drop_table("reviews")
    op.drop_table("analysis_runs")
    op.drop_index("ix_products_category", table_name="products")
    op.drop_table("products")

