import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete

from backend.app.core.database import SessionLocal
from backend.app.models import (
    AnalysisRun,
    Review,
    ReviewAnalysisResult,
    ReviewLabel,
)
from backend.app.repositories.catalog import ReviewRepository
from backend.app.services.months import month_bounds
from backend.app.services.review_classification import review_input_hash

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_sql_aggregation_keeps_versions_separate_and_counts_review_once() -> None:
    review_id = json.loads(
        (PROJECT_ROOT / "data" / "evaluation" / "trial_70.json").read_text(
            encoding="utf-8"
        )
    )["review_ids"][0]
    run_a = "test-aggregate-version-a"
    run_b = "test-aggregate-version-b"
    with SessionLocal() as session:
        review = session.get(Review, review_id)
        assert review is not None
        month = review.reviewed_at.strftime("%Y-%m")
        start, end = month_bounds(month)
        for run_id in (run_a, run_b):
            session.add(
                AnalysisRun(
                    id=run_id,
                    data_version="test-data",
                    model="test-model",
                    prompt_version="test-prompt",
                    label_schema_version="test-schema",
                    source_mode="real",
                    is_active=False,
                    target_review_count=1,
                    config_json={"test": True},
                    status="in_progress",
                )
            )
            session.add(
                ReviewAnalysisResult(
                    id=f"result:{run_id}",
                    run_id=run_id,
                    review_id=review.id,
                    input_hash=review_input_hash(review.title, review.text),
                    status="succeeded",
                    attempt_count=1,
                    input_chars=len(review.text),
                    duration_ms=1,
                    error_history=[],
                    started_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                )
            )
        evidence_a = review.text[: min(12, len(review.text))]
        evidence_b = review.text[-min(12, len(review.text)) :]
        session.add_all(
            [
                ReviewLabel(
                    id="test-label-a1",
                    review_id=review.id,
                    aspect="performance",
                    detail_label="core_performance",
                    polarity="positive",
                    evidence_span=evidence_a,
                    run_id=run_a,
                ),
                ReviewLabel(
                    id="test-label-a2",
                    review_id=review.id,
                    aspect="performance",
                    detail_label="core_performance",
                    polarity="positive",
                    evidence_span=evidence_b,
                    run_id=run_a,
                ),
                ReviewLabel(
                    id="test-label-b1",
                    review_id=review.id,
                    aspect="performance",
                    detail_label="core_performance",
                    polarity="negative",
                    evidence_span=evidence_a,
                    run_id=run_b,
                ),
            ]
        )
        session.commit()

        repository = ReviewRepository(session)
        coverage = repository.analysis_coverage(
            review.product_id, start, end, run_a
        )
        aggregates_a = repository.label_aggregates(
            review.product_id, start, end, run_a
        )
        aggregates_b = repository.label_aggregates(
            review.product_id, start, end, run_b
        )
        assert coverage.succeeded == 1
        assert coverage.total > coverage.succeeded
        assert len(aggregates_a) == 1
        assert aggregates_a[0].polarity == "positive"
        assert aggregates_a[0].count == 1
        assert aggregates_b[0].polarity == "negative"

        session.execute(
            delete(ReviewLabel).where(ReviewLabel.run_id.in_([run_a, run_b]))
        )
        session.execute(delete(AnalysisRun).where(AnalysisRun.id.in_([run_a, run_b])))
        session.commit()
