from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from backend.app.core.database import SessionLocal
from backend.app.services.analysis_sampling import (
    ORIGINAL_EVALUATION_PRODUCTS,
    SampledReview,
    sample_summary,
    select_analysis_sample,
)

OUTPUT_DIR = Path("data/evaluation")
TRIAL_SEED = "reviewshift-absa-trial-v1"
EVALUATION_SEED = "reviewshift-absa-evaluation-v1"
HARD_PATTERN = re.compile(
    r"\b(not|never|but|although|however|stopped|broken|broke|arrived|refund|stars?)\b",
    re.IGNORECASE,
)


def _base_row(item: SampledReview, sample_id: str) -> dict[str, Any]:
    review = item.review
    product = item.product
    return {
        "sample_id": sample_id,
        "product_id": product.id,
        "parent_asin": product.parent_asin,
        "product_name_ko": product.metadata_json.get("title_ko") or "",
        "category": product.category,
        "review_id": review.id,
        "month": review.reviewed_at.strftime("%Y-%m"),
        "rating": review.rating,
        "title_en": review.title or "",
        "text_en": review.text,
        "title_ko_reference": review.title_ko or "",
        "text_ko_reference": review.text_ko or "",
        "translation_notice": "자동 번역 참고용" if review.text_ko else "번역 없음",
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"CSV에 쓸 행이 없습니다: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as session:
        # 평가 표본은 최초 14개 상품 기준으로 고정합니다(상품을 늘려도 과거 표본이 바뀌지 않게).
        scope = set(ORIGINAL_EVALUATION_PRODUCTS)
        trial = select_analysis_sample(
            session, per_product=5, seed=TRIAL_SEED, product_ids=scope
        )
        trial_ids = {item.review.id for item in trial}
        evaluation = select_analysis_sample(
            session,
            per_product=10,
            seed=EVALUATION_SEED,
            exclude_review_ids=trial_ids,
            product_ids=scope,
        )

        # 어려운 사례는 무작위 평가 140건과 분리해 별도의 정성 점검용으로 제공합니다.
        hard_candidates = [
            item
            for item in select_analysis_sample(
                session,
                per_product=5,
                seed="reviewshift-absa-hard-cases-v1",
                exclude_review_ids=trial_ids | {x.review.id for x in evaluation},
                product_ids=scope,
            )
            if HARD_PATTERN.search(f"{item.review.title or ''} {item.review.text}")
        ]

        trial_payload = {
            "seed": TRIAL_SEED,
            "review_ids": [item.review.id for item in trial],
            "summary": sample_summary(trial),
        }
        (OUTPUT_DIR / "trial_70.json").write_text(
            json.dumps(trial_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        blind_rows: list[dict[str, Any]] = []
        prediction_rows: list[dict[str, Any]] = []
        for index, item in enumerate(evaluation, start=1):
            base = _base_row(item, f"evaluation-{index:03d}")
            blind_rows.append(
                {
                    **base,
                    "gold_labels_json": "",
                    "ambiguity_or_error_notes": "",
                    "reviewer": "",
                    "review_status": "pending",
                }
            )
            prediction_rows.append(
                {
                    **base,
                    "prediction_status": "not_run",
                    "analysis_version": "",
                    "predicted_labels_json": "",
                    "model_error": "",
                    "gold_labels_json": "",
                    "comparison_notes": "",
                }
            )
        _write_csv(OUTPUT_DIR / "human_review_blind_140.csv", blind_rows)
        _write_csv(
            OUTPUT_DIR / "human_review_predictions_140.csv", prediction_rows
        )

        hard_rows = [
            {
                **_base_row(item, f"hard-{index:03d}"),
                "check_negation": "",
                "check_mixed_sentiment": "",
                "check_rating_text_conflict": "",
                "check_shipping_vs_product": "",
                "review_notes": "",
            }
            for index, item in enumerate(hard_candidates, start=1)
        ]
        if hard_rows:
            _write_csv(OUTPUT_DIR / "hard_cases_check.csv", hard_rows)

        overlap = trial_ids & {item.review.id for item in evaluation}
        manifest = {
            "trial": sample_summary(trial),
            "evaluation": sample_summary(evaluation),
            "trial_evaluation_overlap_count": len(overlap),
            "hard_cases": len(hard_rows),
            "notes": {
                "blind_file": "사람 정답 입력용이며 모델 예측을 포함하지 않음",
                "prediction_file": "독립 평가 전에는 prediction_status=not_run이며 정확도를 주장하지 않음",
                "hard_cases": "정성 점검용이며 무작위 평가 정확도 계산에 섞지 않음",
            },
        }
        (OUTPUT_DIR / "sample_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"평가 파일 저장: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
