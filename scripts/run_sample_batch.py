"""35개 상품의 AI 분석 표본을 우선순위 단계별로 분류합니다.

- 상품마다 analysis_sample_size(20/30/50/70/100)만큼 표본을 분류합니다(analysis_sample.py 규칙).
- 단계: 모든 상품 20건 → 30건 → 50건 → 70건 → 100건 → 표본 전체. 어느 시점에 멈춰도 모든
  상품에 결과가 있도록 작은 목표부터 채웁니다.
- 이미 성공한 리뷰는 건너뛰므로 중단 후 다시 실행하면 이어서 처리합니다. 마지막에 실패 건을 1회 재시도합니다.

예) python -m scripts.run_sample_batch
"""

from __future__ import annotations

import argparse
import time
from collections import Counter

from sqlalchemy import select

from backend.app.core.categories import REAL_CATEGORY_KEYS
from backend.app.core.database import SessionLocal
from backend.app.models import Product
from backend.app.services.analysis_sample import SamplePlan, build_sample_plan
from backend.app.services.review_classification import OllamaReviewClassifier
from scripts.classify_reviews import (
    DEFAULT_RUN_ID,
    ensure_run,
    ollama_model_identity,
    process_review,
    refresh_run_status,
)

STAGES: tuple[int | None, ...] = (20, 30, 50, 70, 100, None)  # None = 표본 전체(올림 배분분 포함)


def load_plans() -> list[tuple[Product, SamplePlan]]:
    with SessionLocal() as session:
        products = session.scalars(
            select(Product)
            .where(Product.source_mode == "real", Product.category.in_(REAL_CATEGORY_KEYS))
            .order_by(Product.category, Product.id)
        ).all()
        plans = []
        for product in products:
            plan = build_sample_plan(session, product)
            if plan is None:
                raise ValueError(f"analysis_sample_size가 없는 상품입니다: {product.id}")
            plans.append((product, plan))
    return plans


def main() -> None:
    parser = argparse.ArgumentParser(description="상품별 AI 분석 표본을 단계별로 분류합니다.")
    parser.add_argument("--model", default="qwen3.5:latest")
    parser.add_argument("--run-id", default="amazon-absa-qwen35-v3")
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    args = parser.parse_args()
    if args.run_id == DEFAULT_RUN_ID:
        parser.error("표본 분류는 프롬프트 v3 run(amazon-absa-qwen35-v3)을 사용합니다.")

    plans = load_plans()
    total_targets = sum(len(plan.members) for _, plan in plans)
    print(f"상품 {len(plans)}개, 표본 합계 {total_targets}건", flush=True)
    with SessionLocal() as session:
        ensure_run(
            session,
            run_id=args.run_id,
            model=args.model,
            target_review_count=total_targets,
            max_attempts=args.max_attempts,
            timeout_seconds=args.timeout,
            model_identity=ollama_model_identity(args.ollama_url, args.model),
            activate=True,
        )
    classifier = OllamaReviewClassifier(
        model=args.model, base_url=args.ollama_url, timeout_seconds=args.timeout
    )

    started = time.perf_counter()
    counts: Counter[str] = Counter()
    # === [단계별 분류] 작은 목표부터 모든 상품을 채웁니다 ===
    for stage in STAGES:
        label = "표본 전체" if stage is None else f"{stage}건"
        print(f"=== 단계 {label} 시작 ({time.strftime('%Y-%m-%d %H:%M:%S')}) ===", flush=True)
        for product, plan in plans:
            ordered = plan.ordered()
            targets = ordered if stage is None else ordered[: min(stage, plan.size)]
            new = 0
            for review_id in targets:
                outcome = process_review(
                    run_id=args.run_id,
                    review_id=review_id,
                    classifier=classifier,
                    max_attempts=args.max_attempts,
                    retry_failed=False,
                )
                counts[outcome] += 1
                if outcome != "skipped":
                    new += 1
            if new:
                elapsed_hours = (time.perf_counter() - started) / 3600
                print(
                    f"[{label}] {product.id} +{new}건 (누적 성공 {counts['succeeded']}, "
                    f"실패 {counts['failed']}, 경과 {elapsed_hours:.1f}시간)",
                    flush=True,
                )

    # === [실패 재시도] 표본 안의 실패 리뷰만 1회 더 ===
    print("=== 실패 리뷰 재시도 ===", flush=True)
    for product, plan in plans:
        for review_id in plan.ordered():
            outcome = process_review(
                run_id=args.run_id,
                review_id=review_id,
                classifier=classifier,
                max_attempts=args.max_attempts,
                retry_failed=True,
            )
            if outcome != "skipped":
                counts[f"retry_{outcome}"] += 1

    with SessionLocal() as session:
        refresh_run_status(session, args.run_id)
    print(f"완료: {dict(counts)}, 총 {(time.perf_counter() - started) / 3600:.1f}시간", flush=True)


if __name__ == "__main__":
    main()
