from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.categories import REAL_CATEGORY_KEYS
from backend.app.models import Product, Review


@dataclass(frozen=True)
class SampledReview:
    review: Review
    product: Product


def _stable_rank(seed: str, review_id: str) -> str:
    return hashlib.sha256(f"{seed}|{review_id}".encode()).hexdigest()


def _month(review: Review) -> str:
    return review.reviewed_at.strftime("%Y-%m")


def select_analysis_sample(
    session: Session,
    *,
    per_product: int,
    seed: str,
    exclude_review_ids: set[str] | None = None,
) -> list[SampledReview]:
    """14개 상품에서 별점과 월을 분산시킨 재현 가능한 표본을 선택합니다."""
    excluded = exclude_review_ids or set()
    products = list(
        session.scalars(
            select(Product)
            .where(
                Product.source_mode == "real",
                Product.category.in_(REAL_CATEGORY_KEYS),
            )
            .order_by(Product.category, Product.id)
        )
    )
    selected: list[SampledReview] = []
    rating_cycle = [1, 2, 3, 4, 5]
    for product in products:
        candidates = [
            review
            for review in session.scalars(
                select(Review)
                .where(
                    Review.product_id == product.id,
                    Review.eligible.is_(True),
                )
                .order_by(Review.id)
            )
            if review.id not in excluded
        ]
        month_counts: Counter[str] = Counter()
        chosen_ids: set[str] = set()
        for index in range(per_product):
            target_rating = rating_cycle[index % len(rating_cycle)]
            pool = [
                review
                for review in candidates
                if review.id not in chosen_ids and review.rating == target_rating
            ]
            if not pool:
                pool = [review for review in candidates if review.id not in chosen_ids]
            if not pool:
                raise ValueError(f"{product.id}: 표본 {per_product}건을 선택할 수 없습니다.")
            review = min(
                pool,
                key=lambda item: (
                    month_counts[_month(item)],
                    _stable_rank(f"{seed}:{product.id}:{index}", item.id),
                ),
            )
            chosen_ids.add(review.id)
            month_counts[_month(review)] += 1
            selected.append(SampledReview(review=review, product=product))
    return selected


def sample_summary(sample: list[SampledReview]) -> dict[str, object]:
    categories = Counter(item.product.category for item in sample)
    products = Counter(item.product.id for item in sample)
    ratings = Counter(item.review.rating for item in sample)
    months = Counter(_month(item.review) for item in sample)
    return {
        "total": len(sample),
        "categories": dict(sorted(categories.items())),
        "products": dict(sorted(products.items())),
        "ratings": {str(key): value for key, value in sorted(ratings.items())},
        "months": dict(sorted(months.items())),
    }
