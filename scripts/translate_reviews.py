"""리뷰 한국어 번역 배치: 아직 번역이 없는 리뷰를 로컬 LLM으로 번역해 원문과 따로 저장합니다."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime

from sqlalchemy import func, select

from backend.app.core.categories import REAL_CATEGORY_KEYS
from backend.app.core.database import SessionLocal
from backend.app.models import Product, Review
from backend.app.services.review_translation import (
    PROMPT_VERSION,
    OllamaReviewTranslator,
)


# 번역이 없는 리뷰를 카테고리·상품·개수 조건으로 고릅니다.
def pending_reviews(
    *, category: str | None, product_id: str | None, limit: int | None
) -> list[Review]:
    with SessionLocal() as session:
        statement = (
            select(Review)
            .join(Product, Product.id == Review.product_id)
            .where(
                Review.source_mode == "real",
                Review.eligible.is_(True),
                Review.text_ko.is_(None),
                Product.category.in_(REAL_CATEGORY_KEYS),
            )
            # 상세 화면의 첫 페이지부터 한국어가 채워지도록 최신 리뷰를 먼저 처리합니다.
            .order_by(Product.category, Review.product_id, Review.reviewed_at.desc())
        )
        if category:
            statement = statement.where(Product.category == category)
        if product_id:
            statement = statement.where(Review.product_id == product_id)
        if limit is not None:
            statement = statement.limit(limit)
        return list(session.scalars(statement))


# 리뷰 한 건을 번역해 저장합니다.
def translate_one(review_id: str, translator: OllamaReviewTranslator) -> None:
    with SessionLocal() as session:
        review = session.get(Review, review_id)
        if review is None or review.text_ko is not None:
            return
        result = translator.translate(review.title, review.text)
        review.title_ko = result.title_ko
        review.text_ko = result.text_ko
        review.translation_model = translator.model
        review.translation_prompt_version = PROMPT_VERSION
        review.translated_at = datetime.now(UTC)
        session.commit()


# 명령행 옵션으로 대상을 정해 번역을 실행합니다.
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ollama로 실제 Amazon 리뷰를 한국어 번역하고 원문과 별도로 캐시합니다."
    )
    parser.add_argument("--model", default="qwen3.5:latest")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--category", choices=REAL_CATEGORY_KEYS)
    parser.add_argument("--product-id")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--all",
        action="store_true",
        help="제한 없이 남은 리뷰 전체를 처리합니다. CPU에서는 수십 시간이 걸릴 수 있습니다.",
    )
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit은 1 이상이어야 합니다.")

    limit = None if args.all else args.limit
    reviews = pending_reviews(
        category=args.category, product_id=args.product_id, limit=limit
    )
    translator = OllamaReviewTranslator(model=args.model, base_url=args.ollama_url)
    started = time.perf_counter()
    completed = 0
    failed: list[dict[str, str]] = []
    for index, review in enumerate(reviews, start=1):
        item_started = time.perf_counter()
        try:
            translate_one(review.id, translator)
            completed += 1
            print(
                f"[{index}/{len(reviews)}] {review.id} 완료 "
                f"({time.perf_counter() - item_started:.1f}초)",
                flush=True,
            )
        except Exception as exc:  # 한 건 실패가 이미 완료된 번역을 되돌리지 않게 합니다.
            failed.append({"review_id": review.id, "error": str(exc)})
            print(f"[{index}/{len(reviews)}] {review.id} 실패: {exc}", flush=True)

    with SessionLocal() as session:
        translated_total = int(
            session.scalar(
                select(func.count(Review.id))
                .join(Product, Product.id == Review.product_id)
                .where(
                    Review.source_mode == "real",
                    Product.category.in_(REAL_CATEGORY_KEYS),
                    Review.text_ko.is_not(None),
                )
            )
            or 0
        )
    elapsed = time.perf_counter() - started
    print(
        json.dumps(
            {
                "model": args.model,
                "prompt_version": PROMPT_VERSION,
                "requested": len(reviews),
                "completed": completed,
                "failed": failed,
                "elapsed_seconds": round(elapsed, 2),
                "average_seconds": round(elapsed / completed, 2) if completed else None,
                "official_reviews_translated_total": translated_total,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
