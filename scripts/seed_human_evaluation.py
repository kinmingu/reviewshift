"""사람 평가 데이터셋(채점할 리뷰 목록)을 DB에 만드는 스크립트."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from sqlalchemy import select

from backend.app.core.database import SessionLocal
from backend.app.models import HumanReviewEvaluation, Review
from backend.app.services.human_evaluation import DEFAULT_DATASET_ID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BLIND_FILE = PROJECT_ROOT / "data" / "evaluation" / "human_review_blind_140.csv"
TRIAL_FILE = PROJECT_ROOT / "data" / "evaluation" / "trial_70.json"


# 데이터셋 × 리뷰로 평가 행의 고유 ID를 만듭니다.
def _id(dataset_id: str, review_id: str) -> str:
    digest = hashlib.sha256(f"{dataset_id}|{review_id}".encode()).hexdigest()
    return f"human-eval:{digest}"


def seed(dataset_id: str = DEFAULT_DATASET_ID) -> dict[str, int | str]:
    """평가 목록만 넣고, 사람이 작성한 기존 정답은 절대 덮어쓰지 않습니다."""
    trial_ids = set(
        json.loads(TRIAL_FILE.read_text(encoding="utf-8"))["review_ids"]
    )
    with BLIND_FILE.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    evaluation_ids = {row["review_id"] for row in rows}
    overlap = trial_ids & evaluation_ids
    if overlap:
        raise ValueError(f"개발 70건과 독립 평가 140건이 중복됩니다: {len(overlap)}건")

    inserted = 0
    preserved = 0
    with SessionLocal() as session:
        known_reviews = set(
            session.scalars(select(Review.id).where(Review.id.in_(evaluation_ids)))
        )
        missing = evaluation_ids - known_reviews
        if missing:
            raise ValueError(f"DB에 없는 평가 리뷰가 있습니다: {len(missing)}건")
        for position, row in enumerate(rows, start=1):
            existing = session.scalar(
                select(HumanReviewEvaluation).where(
                    HumanReviewEvaluation.dataset_id == dataset_id,
                    HumanReviewEvaluation.review_id == row["review_id"],
                )
            )
            if existing is not None:
                # 위치와 분할 메타데이터만 동기화하고 사람 입력 필드는 보존합니다.
                existing.position = position
                existing.split = "independent_evaluation"
                existing.prompt_tuning_used = False
                preserved += 1
                continue
            session.add(
                HumanReviewEvaluation(
                    id=_id(dataset_id, row["review_id"]),
                    dataset_id=dataset_id,
                    position=position,
                    split="independent_evaluation",
                    review_id=row["review_id"],
                    prompt_tuning_used=False,
                    status="pending",
                    is_normal_empty=False,
                    gold_labels_json=[],
                )
            )
            inserted += 1
        session.commit()
    return {
        "dataset_id": dataset_id,
        "total": len(rows),
        "inserted": inserted,
        "preserved": preserved,
        "trial_overlap": len(overlap),
    }


if __name__ == "__main__":
    print(json.dumps(seed(), ensure_ascii=False, indent=2))
