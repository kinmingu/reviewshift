"""개발 초기 모델 시험용 고정 표본(카테고리·상품·월을 고르게 섞은 70건)을 뽑는 규칙.

지금 서비스 표본 규칙은 analysis_sample.py입니다.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.categories import REAL_CATEGORY_KEYS
from backend.app.models import Product, Review

# 70건 시험·140건 사람 평가 표본을 만든 최초 14개 상품(카테고리별 2개)
ORIGINAL_EVALUATION_PRODUCTS = frozenset(
    {
        "amazon-B08VD2NX25", "amazon-B09M8N7YML", "amazon-B08YGYBQTZ", "amazon-B000FS05VG",
        "amazon-B07NZJ1MHX", "amazon-B08DQGH9T1", "amazon-B0CFTCTHTK", "amazon-B0BWLH7QX5",
        "amazon-B07FC9NRRR", "amazon-B0764PP6R8", "amazon-B087H2LWWZ", "amazon-B00HT5HBMO",
        "amazon-B01EX2IAZM", "amazon-B0B7LC848X",
    }
)


# 표본으로 뽑힌 리뷰와 그 상품.
@dataclass(frozen=True)
class SampledReview:
    review: Review
    product: Product


# seed와 리뷰 ID로 항상 같은 정렬 순서를 만듭니다(무작위처럼 보이지만 재현 가능).
def _stable_rank(seed: str, review_id: str) -> str:
    return hashlib.sha256(f"{seed}|{review_id}".encode()).hexdigest()


# 리뷰 작성 월(YYYY-MM).
def _month(review: Review) -> str:
    return review.reviewed_at.strftime("%Y-%m")


def select_analysis_sample(
    session: Session,
    *,
    per_product: int,
    seed: str,
    exclude_review_ids: set[str] | None = None,
    product_ids: set[str] | None = None,
) -> list[SampledReview]:
    """상품별로 별점과 월을 분산시킨 재현 가능한 평가용 표본을 선택합니다.

    product_ids를 주면 그 상품만 대상으로 합니다. 70건 시험·140건 평가 표본은 최초 14개 상품
    (ORIGINAL_EVALUATION_PRODUCTS) 기준으로 고정되어 있습니다.
    """
    excluded = exclude_review_ids or set()
    products = list(
        session.scalars(
            select(Product)
            .where(
                Product.source_mode == "real",
                Product.category.in_(REAL_CATEGORY_KEYS),
                *([Product.id.in_(sorted(product_ids))] if product_ids is not None else []),
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


# 표본이 카테고리·상품·월·별점별로 몇 건씩인지 요약합니다.
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
