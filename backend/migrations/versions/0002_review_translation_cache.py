"""Add a separate Korean review translation cache.

Revision ID: 0002_review_translation_cache
Revises: 0001_initial
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_review_translation_cache"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 원문 열은 건드리지 않고 번역문과 재현에 필요한 모델·프롬프트 버전을 추가합니다.
    op.add_column("reviews", sa.Column("title_ko", sa.Text(), nullable=True))
    op.add_column("reviews", sa.Column("text_ko", sa.Text(), nullable=True))
    op.add_column(
        "reviews", sa.Column("translation_model", sa.String(length=120), nullable=True)
    )
    op.add_column(
        "reviews",
        sa.Column("translation_prompt_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "reviews", sa.Column("translated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("reviews", "translated_at")
    op.drop_column("reviews", "translation_prompt_version")
    op.drop_column("reviews", "translation_model")
    op.drop_column("reviews", "text_ko")
    op.drop_column("reviews", "title_ko")
