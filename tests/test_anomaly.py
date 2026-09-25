"""불만 이상징후 탐지: Fisher 정확 검정, BH 보정, 판정 규칙, 모든 인접 월 쌍 평가, API."""

import pytest
from fastapi.testclient import TestClient

from backend.app.core.database import SessionLocal
from backend.app.services import anomaly
from backend.app.services.anomaly import (
    AnomalyService,
    benjamini_hochberg,
    classify_level,
    fisher_increase_p,
)


# === [통계] ===
def test_fisher_one_sided_p_values() -> None:
    # 6건 중 1건 → 6건 중 3건: 우연히도 흔한 차이
    assert fisher_increase_p(1, 6, 3, 6) == pytest.approx(0.2727, abs=1e-4)
    # 40건 중 2건 → 40건 중 12건: 유의한 증가
    assert fisher_increase_p(2, 40, 12, 40) < 0.01
    # 감소하면 p값이 큼, 분모가 없거나 불만이 전혀 없으면 1
    assert fisher_increase_p(12, 40, 2, 40) > 0.99
    assert fisher_increase_p(0, 0, 3, 10) == 1.0
    assert fisher_increase_p(0, 10, 0, 10) == 1.0


def test_benjamini_hochberg_keeps_order_and_is_monotone() -> None:
    q = benjamini_hochberg([0.01, 0.04, 0.03, 0.5])
    # 정렬 순위별 p·m/순위를 뒤에서부터 누적 최소로 만든 값: 0.01→0.04, 0.03·0.04→0.0533
    assert q == pytest.approx([0.04, 0.0533333, 0.0533333, 0.5], abs=1e-4)
    assert benjamini_hochberg([]) == []


def test_level_rule() -> None:
    assert classify_level(0.001, 0.05, 15.0, 5) == "anomaly"
    # 보정 후 유의하지 않거나, 증가 폭·건수가 부족하면 이상징후가 아님
    assert classify_level(0.01, 0.2, 15.0, 5) == "watch"
    assert classify_level(0.001, 0.05, 5.0, 5) == "watch"
    assert classify_level(0.001, 0.05, 15.0, 2) == "watch"
    assert classify_level(0.2, 0.5, 15.0, 5) is None
    assert classify_level(0.01, 0.2, -3.0, 5) is None


# === [전체 평가] fixture 상품으로 모든 인접 월 쌍을 평가하는지 확인 ===
def test_report_evaluates_every_adjacent_pair_with_sample_threshold() -> None:
    with SessionLocal() as session:
        strict = AnomalyService(session).report(source_mode="fixture")
        loose = AnomalyService(session, min_analyzed_per_month=5).report(source_mode="fixture")
    # fixture는 달마다 분석 6건이라 기본 기준(10건)으로는 판정하지 않습니다.
    assert strict.pairs_evaluated == 0 and strict.tests == 0
    assert strict.pairs_insufficient >= 1
    assert loose.pairs_evaluated >= 1
    assert loose.tests >= 1
    assert all(item.level in {"anomaly", "watch"} for item in loose.items)
    # 커피메이커 누수 1/6 → 3/6은 우연 범위라 이상징후가 아닙니다.
    assert not any(
        item.detail_label == "carafe leak" and item.level == "anomaly" for item in loose.items
    )


def test_anomaly_api_reports_method_and_counts(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(anomaly, "_cache", None)
    response = client.get("/api/v1/anomalies")
    assert response.status_code == 200
    payload = response.json()
    assert payload["method_version"] == "anomaly-fisher-bh-v1"
    assert "Fisher" in payload["method"]
    assert payload["products_evaluable"] <= payload["products_total"]
