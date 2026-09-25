"""리뷰 의미 검색: 상품·기간 필터 강제, 거리 순 정렬, 입력 검증, 모델 오류 처리.

실제 bge-m3 대신 고정 벡터를 쓰는 가짜 임베더로 테스트 DB의 fixture 리뷰만 사용합니다.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from backend.app.core.database import SessionLocal
from backend.app.models import Review, ReviewEmbedding
from backend.app.models.domain import EMBEDDING_DIMENSIONS
from backend.app.services import review_search
from backend.app.services.embeddings import EmbeddingError, content_hash

MODEL = "bge-m3"


def _vector(axis: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[axis] = 1.0
    return vector


class _FakeEmbedder:
    model = MODEL

    def __init__(self, axis: int = 0, fail: bool = False) -> None:
        self.axis = axis
        self.fail = fail

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise EmbeddingError("응답 시간 초과(테스트)")
        return [_vector(self.axis) for _ in texts]


@pytest.fixture()
def fixture_embeddings() -> Generator[dict[str, int], None, None]:
    """커피메이커 fixture 리뷰마다 서로 다른 축의 벡터를 넣습니다(축 0이 질의와 가장 가까움)."""
    with SessionLocal() as session:
        reviews = session.scalars(
            select(Review).where(Review.source_mode == "fixture").order_by(Review.id)
        ).all()
        axes: dict[str, int] = {}
        for axis, review in enumerate(reviews):
            axes[review.id] = axis
            session.add(
                ReviewEmbedding(
                    id=f"test-embedding:{review.id}",
                    review_id=review.id,
                    model=MODEL,
                    content_hash=content_hash(review.title, review.text),
                    embedding=_vector(axis),
                )
            )
        session.commit()
    yield axes
    with SessionLocal() as session:
        session.execute(delete(ReviewEmbedding).where(ReviewEmbedding.id.like("test-embedding:%")))
        session.commit()


def _use_embedder(monkeypatch: pytest.MonkeyPatch, embedder: _FakeEmbedder) -> None:
    monkeypatch.setattr(review_search, "OllamaEmbedder", lambda **_: embedder)


def test_search_is_limited_to_product_and_months(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, fixture_embeddings: dict[str, int]
) -> None:
    # 전체 fixture 중 가장 가까운(축 0) 리뷰의 상품·월 밖에 있는 리뷰는 절대 나오면 안 됩니다.
    closest_id = min(fixture_embeddings, key=fixture_embeddings.get)
    with SessionLocal() as session:
        closest = session.get(Review, closest_id)
        assert closest is not None
        product_id = closest.product_id
    _use_embedder(monkeypatch, _FakeEmbedder(axis=fixture_embeddings[closest_id]))

    response = client.get(
        f"/api/v1/products/{product_id}/search",
        params={"q": "leaking carafe", "month": ["2025-02"], "limit": 30},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["months"] == ["2025-02"]
    assert payload["embedding_model"] == MODEL
    items = payload["items"]
    assert items
    assert all(item["review"]["reviewed_at"].startswith("2025-02") for item in items)
    with SessionLocal() as session:
        product_ids = {session.get(Review, item["review"]["id"]).product_id for item in items}
    assert product_ids == {product_id}
    similarities = [item["similarity"] for item in items]
    assert similarities == sorted(similarities, reverse=True)


def test_search_requires_month_and_query(client: TestClient) -> None:
    missing_month = client.get(
        "/api/v1/products/fixture-prod-coffee/search", params={"q": "leak"}
    )
    assert missing_month.status_code == 422
    blank = client.get(
        "/api/v1/products/fixture-prod-coffee/search", params={"q": "   ", "month": "2025-02"}
    )
    assert blank.status_code == 422
    bad_month = client.get(
        "/api/v1/products/fixture-prod-coffee/search", params={"q": "leak", "month": "2025-13"}
    )
    assert bad_month.status_code == 422


def test_search_reports_embedding_model_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_embedder(monkeypatch, _FakeEmbedder(fail=True))
    response = client.get(
        "/api/v1/products/fixture-prod-coffee/search", params={"q": "leak", "month": "2025-02"}
    )
    assert response.status_code == 503
    assert "임베딩" in response.json()["detail"]


def test_search_for_missing_product_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_embedder(monkeypatch, _FakeEmbedder())
    response = client.get(
        "/api/v1/products/not-a-product/search", params={"q": "leak", "month": "2025-02"}
    )
    assert response.status_code == 404
