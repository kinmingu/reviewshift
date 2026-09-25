"""상품별 AI 분석 표본(재현 가능한 비율 표본).

규칙(결과를 보기 전에 정함)
- 상품 메타데이터의 analysis_sample_size만큼 분석합니다. 값이 없으면 저장 리뷰 전체가 대상입니다.
- 각 달의 리뷰 수에 비례해 배분합니다(올림, 그 달 리뷰 수 이하). 그래서 합계는 목표 이상입니다.
- 달 안에서는 SHA-256(review_id) 순서로 고릅니다. 날짜와 무관하지만 누가 실행해도 같습니다.
- 분류 순서(processing_order)도 같은 해시를 쓰므로, 먼저 분류된 리뷰가 곧 표본의 앞부분입니다.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Product, Review


def processing_order_key(review_id: str) -> str:
    return hashlib.sha256(f"reviewshift-processing-order|{review_id}".encode()).hexdigest()


def month_quotas(month_counts: dict[str, int], size: int) -> dict[str, int]:
    """목표 수를 월별 리뷰 수에 비례해 올림 배분합니다(합계 ≥ 목표, 각 달 ≤ 그 달 리뷰 수)."""
    total = sum(month_counts.values())
    if total == 0:
        return {month: 0 for month in month_counts}
    if size >= total:
        return dict(month_counts)
    return {
        month: min(count, math.ceil(size * count / total)) for month, count in month_counts.items()
    }


@dataclass(frozen=True)
class SamplePlan:
    size: int
    by_month: dict[str, list[str]]  # 월 → 표본 리뷰 ID(해시 순서)

    @property
    def members(self) -> set[str]:
        return {review_id for ids in self.by_month.values() for review_id in ids}

    def ordered(self) -> list[str]:
        """분류 우선순위: 앞부분만 처리해도 각 달이 비율대로 채워지도록 섞은 순서."""
        positions = [
            ((index + 0.5) / len(ids), month, review_id)
            for month, ids in self.by_month.items()
            for index, review_id in enumerate(ids)
        ]
        return [review_id for _, _, review_id in sorted(positions)]


def build_sample_plan(session: Session, product: Product) -> SamplePlan | None:
    size = product.metadata_json.get("analysis_sample_size")
    if not size:
        return None
    rows = session.execute(
        select(Review.id, Review.reviewed_at).where(
            Review.product_id == product.id, Review.eligible.is_(True)
        )
    ).all()
    grouped: dict[str, list[str]] = {}
    for review_id, reviewed_at in rows:
        grouped.setdefault(reviewed_at.astimezone(UTC).strftime("%Y-%m"), []).append(review_id)
    quotas = month_quotas({month: len(ids) for month, ids in grouped.items()}, int(size))
    return SamplePlan(
        size=int(size),
        by_month={
            month: sorted(ids, key=processing_order_key)[: quotas[month]]
            for month, ids in sorted(grouped.items())
        },
    )
