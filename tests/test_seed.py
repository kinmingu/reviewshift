from sqlalchemy import func, select

from backend.app.core.database import SessionLocal
from backend.app.fixtures import FIXTURE_RUN_ID, seed_fixtures
from backend.app.models import Product, Review, ReviewLabel


def _counts() -> tuple[int, int, int]:
    with SessionLocal() as session:
        return (
            int(
                session.scalar(
                    select(func.count(Product.id)).where(Product.source_mode == "fixture")
                )
                or 0
            ),
            int(
                session.scalar(
                    select(func.count(Review.id)).where(Review.source_mode == "fixture")
                )
                or 0
            ),
            int(
                session.scalar(
                    select(func.count(ReviewLabel.id)).where(
                        ReviewLabel.run_id == FIXTURE_RUN_ID
                    )
                )
                or 0
            ),
        )


def test_fixture_seed_is_idempotent() -> None:
    before = _counts()
    with SessionLocal() as session:
        result = seed_fixtures(session)
    after = _counts()
    assert result == {"products": 3, "reviews": 36, "labels": 43}
    assert before == after == (3, 36, 43)
