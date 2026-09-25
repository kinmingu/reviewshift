import pytest

from backend.app.core.database import SessionLocal
from backend.app.services.analysis_sampling import (
    ORIGINAL_EVALUATION_PRODUCTS,
    sample_summary,
    select_analysis_sample,
)

pytestmark = pytest.mark.real_data


def test_trial_and_evaluation_samples_are_balanced_and_disjoint() -> None:
    with SessionLocal() as session:
        trial = select_analysis_sample(
            session, per_product=5,
            seed="reviewshift-absa-trial-v1",
            product_ids=set(ORIGINAL_EVALUATION_PRODUCTS),
        )
        evaluation = select_analysis_sample(
            session,
            per_product=10,
            seed="reviewshift-absa-evaluation-v1",
            exclude_review_ids={item.review.id for item in trial},
            product_ids=set(ORIGINAL_EVALUATION_PRODUCTS),
        )

    trial_summary = sample_summary(trial)
    evaluation_summary = sample_summary(evaluation)
    assert trial_summary["total"] == 70
    assert set(trial_summary["categories"].values()) == {10}  # type: ignore[union-attr]
    assert set(trial_summary["products"].values()) == {5}  # type: ignore[union-attr]
    assert trial_summary["ratings"] == {str(value): 14 for value in range(1, 6)}
    assert evaluation_summary["total"] == 140
    assert set(evaluation_summary["products"].values()) == {10}  # type: ignore[union-attr]
    assert {item.review.id for item in trial}.isdisjoint(
        {item.review.id for item in evaluation}
    )
