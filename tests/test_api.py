import pytest
from fastapi.testclient import TestClient


def test_health_reports_database_connection(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_categories_are_fixture_labeled(client: TestClient) -> None:
    response = client.get("/api/v1/categories")
    assert response.status_code == 200
    assert response.json() == {
        "items": ["Home Appliances", "Kitchen Appliances"],
        "source_mode": "fixture",
    }


def test_product_search_and_category_filter(client: TestClient) -> None:
    all_products = client.get("/api/v1/products", params={"page": 1, "page_size": 2})
    assert all_products.status_code == 200
    assert all_products.json()["total"] == 3
    assert len(all_products.json()["items"]) == 2
    assert all(item["source_mode"] == "fixture" for item in all_products.json()["items"])

    searched = client.get("/api/v1/products", params={"query": "Coffee"})
    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    assert searched.json()["items"][0]["id"] == "fixture-prod-coffee"

    filtered = client.get(
        "/api/v1/products", params={"category": "Home Appliances"}
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == "fixture-prod-vacuum"


def test_product_detail_exposes_real_fixture_months(client: TestClient) -> None:
    response = client.get("/api/v1/products/fixture-prod-coffee")
    assert response.status_code == 200
    payload = response.json()
    assert payload["available_months"] == ["2025-01", "2025-02"]
    assert payload["review_count"] == 12
    assert payload["metadata"]["fixture"] is True


def test_missing_product_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/products/not-a-product")
    assert response.status_code == 404


def test_invalid_month_returns_422(client: TestClient) -> None:
    response = client.get(
        "/api/v1/products/fixture-prod-coffee/comparison",
        params={"target_month": "2025-13", "baseline_month": "2025-01"},
    )
    assert response.status_code == 422


def _issue(payload: dict, aspect: str, detail: str, polarity: str) -> dict:
    return next(
        item
        for item in payload["issues"]
        if (item["aspect"], item["detail_label"], item["polarity"])
        == (aspect, detail, polarity)
    )


def test_comparison_is_aggregated_from_distinct_reviews(client: TestClient) -> None:
    response = client.get(
        "/api/v1/products/fixture-prod-coffee/comparison",
        params={"target_month": "2025-02", "baseline_month": "2025-01"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_mode"] == "fixture"
    assert payload["status"] == "ok"
    assert payload["coverage"] == {
        "target_total": 6,
        "target_labeled": 6,
        "baseline_total": 6,
        "baseline_labeled": 6,
        "target_average_rating": pytest.approx(17 / 6),
        "baseline_average_rating": pytest.approx(4.0),
    }

    leak = _issue(payload, "reliability", "carafe leak", "negative")
    assert leak["target_count"] == 3
    assert leak["baseline_count"] == 1
    assert leak["target_rate"] == pytest.approx(0.5)
    assert leak["baseline_rate"] == pytest.approx(1 / 6)
    assert leak["change_pp"] == pytest.approx(100 / 3)
    assert len(leak["evidence_review_ids"]) == 4


def test_zero_baseline_issue_is_not_divided_by_zero(client: TestClient) -> None:
    response = client.get(
        "/api/v1/products/fixture-prod-coffee/comparison",
        params={"target_month": "2025-02", "baseline_month": "2025-01"},
    )
    odor = _issue(response.json(), "material", "plastic odor", "negative")
    assert odor["baseline_count"] == 0
    assert odor["baseline_rate"] == 0
    assert odor["target_count"] == 1
    assert odor["change_pp"] == pytest.approx(100 / 6)


def test_empty_month_returns_insufficient_data(client: TestClient) -> None:
    response = client.get(
        "/api/v1/products/fixture-prod-coffee/comparison",
        params={"target_month": "2025-03", "baseline_month": "2025-01"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "insufficient_data"
    assert payload["coverage"]["target_total"] == 0
    assert payload["issues"] == []


def test_review_filter_returns_original_evidence(client: TestClient) -> None:
    response = client.get(
        "/api/v1/products/fixture-prod-coffee/reviews",
        params={
            "month": "2025-02",
            "aspect": "reliability",
            "polarity": "negative",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_mode"] == "fixture"
    assert payload["total"] == 3
    wet_counter = next(
        item for item in payload["items"] if item["id"] == "coffee-2025-02-01"
    )
    leak_labels = [
        label
        for label in wet_counter["labels"]
        if label["detail_label"] == "carafe leak"
    ]
    assert len(leak_labels) == 2
    assert all(label["evidence_span"] in wet_counter["text"] for label in leak_labels)


def test_real_products_are_separate_and_unclassified(client: TestClient) -> None:
    response = client.get("/api/v1/products", params={"source_mode": "real"})
    assert response.status_code == 200
    payload = response.json()
    expected_ids = {
        "amazon-B0B3DB5HTC",
        "amazon-B0C57WMPJQ",
        "amazon-B07WTXWC32",
    }
    assert expected_ids <= {item["id"] for item in payload["items"]}
    assert all(item["source_mode"] == "real" for item in payload["items"])

    detail = client.get("/api/v1/products/amazon-B0C57WMPJQ").json()
    assert detail["source_mode"] == "real"
    assert len(detail["monthly_stats"]) == 12
    august = next(item for item in detail["monthly_stats"] if item["month"] == "2022-08")
    assert august["review_count"] > 0
    assert 1 <= august["average_rating"] <= 5

    reviews = client.get(
        "/api/v1/products/amazon-B0C57WMPJQ/reviews",
        params={"month": "2022-08", "page_size": 5},
    ).json()
    assert reviews["source_mode"] == "real"
    assert reviews["total"] == august["review_count"]
    assert all(item["labels"] == [] for item in reviews["items"])

    comparison = client.get(
        "/api/v1/products/amazon-B0C57WMPJQ/comparison",
        params={"target_month": "2022-08", "baseline_month": "2022-07"},
    ).json()
    assert comparison["status"] == "insufficient_data"
    assert comparison["issues"] == []
    assert comparison["analysis_version"] == "not-analyzed"
    assert comparison["coverage"]["target_labeled"] == 0
    assert comparison["coverage"]["target_average_rating"] is not None
