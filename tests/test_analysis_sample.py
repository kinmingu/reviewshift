"""상품별 AI 분석 표본: 월별 비례 배분, 우선순위 순서, 표본 기준 완료 판정·집계, 표본 부족 신호."""

from collections import Counter

from fastapi.testclient import TestClient

from backend.app.core.database import SessionLocal
from backend.app.models import Product
from backend.app.services.analysis_sample import (
    SamplePlan,
    build_sample_plan,
    month_quotas,
    processing_order_key,
)

PRODUCT = "fixture-prod-coffee"


# === [배분 규칙] ===
def test_month_quotas_are_proportional_and_never_below_target() -> None:
    quotas = month_quotas({"2021-12": 140, "2022-01": 166, "2022-02": 67}, 100)
    assert quotas == {"2021-12": 38, "2022-01": 45, "2022-02": 18}
    assert sum(quotas.values()) >= 100
    # 목표가 전체보다 크면 전체가 표본입니다.
    assert month_quotas({"a": 3, "b": 2}, 20) == {"a": 3, "b": 2}
    assert month_quotas({}, 20) == {}


def test_ordered_prefix_keeps_month_balance() -> None:
    plan = SamplePlan(
        size=100,
        by_month={
            "2021-12": [f"d{i}" for i in range(38)],
            "2022-01": [f"j{i}" for i in range(45)],
            "2022-02": [f"f{i}" for i in range(18)],
        },
    )
    ordered = plan.ordered()
    assert len(ordered) == 101 and set(ordered) == plan.members
    # 앞 20건만 처리해도 각 달이 비율대로(±1) 섞여 있습니다.
    first = Counter(item[0] for item in ordered[:20])
    assert abs(first["d"] - 20 * 38 / 101) <= 1
    assert abs(first["j"] - 20 * 45 / 101) <= 1
    assert abs(first["f"] - 20 * 18 / 101) <= 1
    # 같은 달 안에서는 원래(해시) 순서를 유지합니다.
    assert [item for item in ordered if item.startswith("j")] == plan.by_month["2022-01"]


# === [표본 기준 집계] fixture 상품에 임시로 표본 3건/월을 지정해 확인합니다 ===
def _set_sample_size(size: int | None) -> None:
    with SessionLocal() as session:
        product = session.get(Product, PRODUCT)
        assert product is not None
        metadata = dict(product.metadata_json)
        if size is None:
            metadata.pop("analysis_sample_size", None)
        else:
            metadata["analysis_sample_size"] = size
        product.metadata_json = metadata
        session.commit()


def test_sample_plan_uses_hash_order_within_month() -> None:
    _set_sample_size(6)
    try:
        with SessionLocal() as session:
            product = session.get(Product, PRODUCT)
            plan = build_sample_plan(session, product)
        assert plan is not None
        assert {month: len(ids) for month, ids in plan.by_month.items()} == {
            "2025-01": 3,
            "2025-02": 3,
        }
        for ids in plan.by_month.values():
            assert ids == sorted(ids, key=processing_order_key)
    finally:
        _set_sample_size(None)


def test_comparison_and_insights_count_only_sample(client: TestClient) -> None:
    _set_sample_size(6)
    try:
        comparison = client.get(
            f"/api/v1/products/{PRODUCT}/comparison",
            params={"target_month": "2025-02", "baseline_month": "2025-01"},
        ).json()
        coverage = comparison["coverage"]
        # 전체 리뷰 수는 그대로, 분석 대상·성공은 표본 3건 기준
        assert coverage["target_total"] == 6
        assert coverage["target_succeeded"] == 3
        assert coverage["target_unprocessed"] == 0
        assert coverage["target_analysis_status"] == "complete"
        assert all(item["target_count"] <= 3 for item in comparison["issues"])
        # 표본을 다 분석했지만 월 3건은 비교 기준(30건)에 못 미치므로 '표본 부족'
        assert comparison["signal_status"] == "insufficient_sample"

        insights = client.get(f"/api/v1/products/{PRODUCT}/insights").json()
        assert insights["analysis"]["sample_size"] == 6
        assert insights["analysis"]["stored_reviews"] == 12
        assert insights["analysis"]["succeeded"] == 6
        assert insights["analysis"]["status"] == "complete"
        assert all(month["analyzed_count"] == 3 for month in insights["monthly"])

        reviews = client.get(
            f"/api/v1/products/{PRODUCT}/reviews", params={"month": "2025-02"}
        ).json()["items"]
        assert sum(item["in_analysis_sample"] is True for item in reviews) == 3
    finally:
        _set_sample_size(None)
    # 표본을 지정하지 않은 상품은 기존처럼 전체 리뷰가 대상입니다.
    full = client.get(f"/api/v1/products/{PRODUCT}/insights").json()
    assert full["analysis"]["sample_size"] is None
    assert full["analysis"]["succeeded"] == 12
