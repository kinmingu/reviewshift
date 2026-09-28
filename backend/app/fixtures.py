"""테스트·데모용 합성(fixture) 데이터: 가짜 상품 3개와 리뷰·라벨.

실제 아마존 데이터와 섞이지 않도록 source_mode='fixture'로 구분해 저장합니다.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.models import (
    AnalysisRun,
    Product,
    Review,
    ReviewAnalysisResult,
    ReviewLabel,
)
from backend.app.services.review_classification import review_input_hash

FIXTURE_RUN_ID = "fixture-analysis-v1"
FIXTURE_DATA_VERSION = "fixture-2026-09-v1"


# 합성 리뷰 한 건의 정의(본문과 미리 정한 정답 라벨).
@dataclass(frozen=True)
class ReviewFixture:
    id: str
    product_id: str
    asin: str
    reviewed_at: datetime
    rating: int
    title: str
    text: str
    labels: tuple[tuple[str, str, str, str], ...]


# '2024-01-15T..' 같은 문자열을 UTC 시각으로 바꿉니다.
def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


PRODUCTS = (
    Product(
        id="fixture-prod-coffee",
        source="synthetic-test-fixture",
        source_mode="fixture",
        parent_asin="FIXTURE-COFFEE-001",
        title="AeroBrew 12-Cup Coffee Maker",
        category="Kitchen Appliances",
        image_url=None,
        metadata_json={"fixture": True, "brand": "DemoLab"},
    ),
    Product(
        id="fixture-prod-airfryer",
        source="synthetic-test-fixture",
        source_mode="fixture",
        parent_asin="FIXTURE-AIRFRYER-001",
        title="CrispWave 5L Air Fryer",
        category="Kitchen Appliances",
        image_url=None,
        metadata_json={"fixture": True, "brand": "DemoLab"},
    ),
    Product(
        id="fixture-prod-vacuum",
        source="synthetic-test-fixture",
        source_mode="fixture",
        parent_asin="FIXTURE-VACUUM-001",
        title="CleanGo Cordless Vacuum",
        category="Home Appliances",
        image_url=None,
        metadata_json={"fixture": True, "brand": "DemoLab"},
    ),
)


REVIEWS = (
    ReviewFixture("coffee-2025-01-01", "fixture-prod-coffee", "FIX-C01", _dt("2025-01-03T10:00:00"), 5, "Fast and hot", "Brews quickly and keeps the coffee hot.", (("performance", "brewing speed", "positive", "Brews quickly"), ("temperature", "heat retention", "positive", "keeps the coffee hot"))),
    ReviewFixture("coffee-2025-01-02", "fixture-prod-coffee", "FIX-C01", _dt("2025-01-08T11:00:00"), 4, "Clean pour", "The carafe pours cleanly and the controls are simple.", (("usability", "pouring", "positive", "pours cleanly"), ("usability", "controls", "positive", "controls are simple"))),
    ReviewFixture("coffee-2025-01-03", "fixture-prod-coffee", "FIX-C01", _dt("2025-01-12T12:00:00"), 2, "Small leak", "A small drip leaked from the carafe after pouring.", (("reliability", "carafe leak", "negative", "drip leaked from the carafe"),)),
    ReviewFixture("coffee-2025-01-04", "fixture-prod-coffee", "FIX-C01", _dt("2025-01-17T13:00:00"), 5, "Easy morning", "The timer is easy to set before bed.", (("usability", "timer", "positive", "timer is easy to set"),)),
    ReviewFixture("coffee-2025-01-05", "fixture-prod-coffee", "FIX-C01", _dt("2025-01-22T14:00:00"), 4, "Good flavor", "Coffee tastes balanced and the filter basket is easy to remove.", (("quality", "taste", "positive", "tastes balanced"), ("usability", "cleaning", "positive", "filter basket is easy to remove"))),
    ReviewFixture("coffee-2025-01-06", "fixture-prod-coffee", "FIX-C01", _dt("2025-01-27T15:00:00"), 4, "Warm pot", "The warming plate kept the second cup hot.", (("temperature", "heat retention", "positive", "kept the second cup hot"),)),
    ReviewFixture("coffee-2025-02-01", "fixture-prod-coffee", "FIX-C01", _dt("2025-02-02T10:00:00"), 1, "Wet counter", "Water leaked under the carafe and the counter was wet.", (("reliability", "carafe leak", "negative", "Water leaked under the carafe"), ("reliability", "carafe leak", "negative", "counter was wet"))),
    ReviewFixture("coffee-2025-02-02", "fixture-prod-coffee", "FIX-C01", _dt("2025-02-07T11:00:00"), 2, "Valve drip", "The valve drips whenever I remove the pot.", (("reliability", "carafe leak", "negative", "valve drips"),)),
    ReviewFixture("coffee-2025-02-03", "fixture-prod-coffee", "FIX-C01", _dt("2025-02-13T12:00:00"), 2, "Leaks after brewing", "The carafe leaks after every brew although the coffee is hot.", (("reliability", "carafe leak", "negative", "carafe leaks after every brew"), ("temperature", "heat retention", "positive", "coffee is hot"))),
    ReviewFixture("coffee-2025-02-04", "fixture-prod-coffee", "FIX-C01", _dt("2025-02-18T13:00:00"), 3, "Plastic smell", "A plastic odor remains after several cleaning cycles.", (("material", "plastic odor", "negative", "plastic odor remains"),)),
    ReviewFixture("coffee-2025-02-05", "fixture-prod-coffee", "FIX-C01", _dt("2025-02-23T14:00:00"), 5, "Simple timer", "The timer and buttons are straightforward.", (("usability", "controls", "positive", "buttons are straightforward"),)),
    ReviewFixture("coffee-2025-02-06", "fixture-prod-coffee", "FIX-C01", _dt("2025-02-27T15:00:00"), 4, "Quick brew", "It finishes a full pot quickly.", (("performance", "brewing speed", "positive", "finishes a full pot quickly"),)),
    ReviewFixture("airfryer-2025-01-01", "fixture-prod-airfryer", "FIX-A01", _dt("2025-01-02T09:00:00"), 2, "Very loud", "The fan is loud throughout cooking.", (("noise", "fan noise", "negative", "fan is loud"),)),
    ReviewFixture("airfryer-2025-01-02", "fixture-prod-airfryer", "FIX-A01", _dt("2025-01-07T09:30:00"), 2, "Rattling", "It makes a rattling noise at high heat.", (("noise", "fan noise", "negative", "rattling noise"),)),
    ReviewFixture("airfryer-2025-01-03", "fixture-prod-airfryer", "FIX-A01", _dt("2025-01-12T10:00:00"), 3, "Noisy but crisp", "The motor sounds noisy but fries turn crisp.", (("noise", "fan noise", "negative", "motor sounds noisy"), ("cooking", "crispness", "positive", "fries turn crisp"))),
    ReviewFixture("airfryer-2025-01-04", "fixture-prod-airfryer", "FIX-A01", _dt("2025-01-17T10:30:00"), 5, "Even cooking", "Chicken cooked evenly on both sides.", (("cooking", "evenness", "positive", "cooked evenly"),)),
    ReviewFixture("airfryer-2025-01-05", "fixture-prod-airfryer", "FIX-A01", _dt("2025-01-22T11:00:00"), 4, "Easy basket", "The basket is easy to clean.", (("usability", "cleaning", "positive", "basket is easy to clean"),)),
    ReviewFixture("airfryer-2025-01-06", "fixture-prod-airfryer", "FIX-A01", _dt("2025-01-27T11:30:00"), 3, "Small capacity", "The basket feels small for a family meal.", (("capacity", "basket size", "negative", "basket feels small"),)),
    ReviewFixture("airfryer-2025-02-01", "fixture-prod-airfryer", "FIX-A01", _dt("2025-02-03T09:00:00"), 2, "One noisy unit", "The fan still sounds loud at maximum temperature.", (("noise", "fan noise", "negative", "fan still sounds loud"),)),
    ReviewFixture("airfryer-2025-02-02", "fixture-prod-airfryer", "FIX-A01", _dt("2025-02-08T09:30:00"), 5, "Crispy wings", "Wings came out crisp with very little oil.", (("cooking", "crispness", "positive", "Wings came out crisp"),)),
    ReviewFixture("airfryer-2025-02-03", "fixture-prod-airfryer", "FIX-A01", _dt("2025-02-13T10:00:00"), 5, "Even vegetables", "Vegetables cooked evenly without burning.", (("cooking", "evenness", "positive", "cooked evenly"),)),
    ReviewFixture("airfryer-2025-02-04", "fixture-prod-airfryer", "FIX-A01", _dt("2025-02-18T10:30:00"), 4, "Good results", "Fries are crisp and the preset is convenient.", (("cooking", "crispness", "positive", "Fries are crisp"), ("usability", "presets", "positive", "preset is convenient"))),
    ReviewFixture("airfryer-2025-02-05", "fixture-prod-airfryer", "FIX-A01", _dt("2025-02-23T11:00:00"), 4, "Easy cleanup", "The nonstick basket wipes clean quickly.", (("usability", "cleaning", "positive", "basket wipes clean quickly"),)),
    ReviewFixture("airfryer-2025-02-06", "fixture-prod-airfryer", "FIX-A01", _dt("2025-02-27T11:30:00"), 5, "Reliable dinner", "Fish cooked evenly and stayed moist.", (("cooking", "evenness", "positive", "Fish cooked evenly"),)),
    ReviewFixture("vacuum-2025-01-01", "fixture-prod-vacuum", "FIX-V01", _dt("2025-01-04T08:00:00"), 5, "Strong pickup", "Suction is strong on carpet.", (("performance", "suction", "positive", "Suction is strong"),)),
    ReviewFixture("vacuum-2025-01-02", "fixture-prod-vacuum", "FIX-V01", _dt("2025-01-09T08:30:00"), 5, "Great floors", "It picks up crumbs from hard floors easily.", (("performance", "suction", "positive", "picks up crumbs"),)),
    ReviewFixture("vacuum-2025-01-03", "fixture-prod-vacuum", "FIX-V01", _dt("2025-01-14T09:00:00"), 4, "Useful power", "The suction handles pet hair well.", (("performance", "suction", "positive", "handles pet hair well"),)),
    ReviewFixture("vacuum-2025-01-04", "fixture-prod-vacuum", "FIX-V01", _dt("2025-01-19T09:30:00"), 4, "Light body", "The vacuum is light enough for stairs.", (("usability", "weight", "positive", "light enough for stairs"),)),
    ReviewFixture("vacuum-2025-01-05", "fixture-prod-vacuum", "FIX-V01", _dt("2025-01-24T10:00:00"), 2, "Short battery", "The battery died before I finished two rooms.", (("battery", "runtime", "negative", "battery died before I finished"),)),
    ReviewFixture("vacuum-2025-01-06", "fixture-prod-vacuum", "FIX-V01", _dt("2025-01-29T10:30:00"), 5, "Clean sofa", "Strong suction removed dust from the sofa.", (("performance", "suction", "positive", "Strong suction"),)),
    ReviewFixture("vacuum-2025-02-01", "fixture-prod-vacuum", "FIX-V01", _dt("2025-02-04T08:00:00"), 2, "Battery fades", "The battery fades after fifteen minutes.", (("battery", "runtime", "negative", "battery fades after fifteen minutes"),)),
    ReviewFixture("vacuum-2025-02-02", "fixture-prod-vacuum", "FIX-V01", _dt("2025-02-09T08:30:00"), 1, "Cannot finish", "Battery runtime is too short to finish the apartment.", (("battery", "runtime", "negative", "runtime is too short"),)),
    ReviewFixture("vacuum-2025-02-03", "fixture-prod-vacuum", "FIX-V01", _dt("2025-02-14T09:00:00"), 2, "Needs charging", "It needs charging halfway through cleaning.", (("battery", "runtime", "negative", "needs charging halfway"),)),
    ReviewFixture("vacuum-2025-02-04", "fixture-prod-vacuum", "FIX-V01", _dt("2025-02-19T09:30:00"), 5, "Good carpet pickup", "Suction remains strong on rugs.", (("performance", "suction", "positive", "Suction remains strong"),)),
    ReviewFixture("vacuum-2025-02-05", "fixture-prod-vacuum", "FIX-V01", _dt("2025-02-24T10:00:00"), 4, "Easy stairs", "The light body is convenient on stairs.", (("usability", "weight", "positive", "light body is convenient"),)),
    ReviewFixture("vacuum-2025-02-06", "fixture-prod-vacuum", "FIX-V01", _dt("2025-02-27T10:30:00"), 4, "Picks up hair", "It picks up pet hair from carpet well.", (("performance", "suction", "positive", "picks up pet hair"),)),
)


# 합성 상품·리뷰·라벨을 DB에 넣습니다(근거 문장이 본문에 있는지 먼저 검사).
def seed_fixtures(session: Session) -> dict[str, int]:
    for fixture in REVIEWS:
        for _, _, _, evidence in fixture.labels:
            if evidence not in fixture.text:
                raise ValueError(f"evidence is not present in review {fixture.id}: {evidence}")

    for product in PRODUCTS:
        session.merge(product)
    session.merge(
        AnalysisRun(
            id=FIXTURE_RUN_ID,
            data_version=FIXTURE_DATA_VERSION,
            model="deterministic-fixture-labels",
            prompt_version="not-applicable",
            label_schema_version="fixture-label-schema-v1",
            source_mode="fixture",
            is_active=True,
            target_review_count=len(REVIEWS),
            config_json={"fixture": True},
            status="completed",
        )
    )
    session.commit()

    for fixture in REVIEWS:
        session.merge(
            Review(
                id=fixture.id,
                product_id=fixture.product_id,
                source_record_key=f"synthetic:{fixture.id}",
                source_mode="fixture",
                asin=fixture.asin,
                title=fixture.title,
                text=fixture.text,
                rating=fixture.rating,
                reviewed_at=fixture.reviewed_at,
                eligible=True,
            )
        )
    session.commit()

    label_count = 0
    for fixture in REVIEWS:
        session.merge(
            ReviewAnalysisResult(
                id=f"fixture-result:{fixture.id}",
                run_id=FIXTURE_RUN_ID,
                review_id=fixture.id,
                input_hash=review_input_hash(fixture.title, fixture.text),
                status="succeeded",
                attempt_count=1,
                input_chars=len(fixture.title) + len(fixture.text),
                duration_ms=0,
                error_history=[],
                raw_response='{"source":"deterministic-fixture"}',
                started_at=fixture.reviewed_at,
                completed_at=fixture.reviewed_at,
            )
        )
        for index, (aspect, detail, polarity, evidence) in enumerate(fixture.labels, start=1):
            session.merge(
                ReviewLabel(
                    id=f"fixture-label:{fixture.id}:{index}",
                    review_id=fixture.id,
                    aspect=aspect,
                    detail_label=detail,
                    polarity=polarity,
                    evidence_span=evidence,
                    run_id=FIXTURE_RUN_ID,
                )
            )
            label_count += 1
    session.commit()
    return {"products": len(PRODUCTS), "reviews": len(REVIEWS), "labels": label_count}
