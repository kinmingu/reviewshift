"""즉시 답변(LLM 없음): 질문→분석 항목 연결, DB 집계·근거, 관련 리뷰, FAQ 연결, MCP 경유 API."""

import pytest
from fastapi.testclient import TestClient

from backend.app.core.database import SessionLocal
from backend.app.models.domain import EMBEDDING_DIMENSIONS
from backend.app.services import quick_answer
from backend.app.services.quick_answer import QuickAnswerService

PRODUCT = "fixture-prod-coffee"
# 단어가 들어 있으면 해당 축이 커지는 가짜 임베딩(질문과 항목 설명의 의미 비교를 흉내)
AXES = {"배송": 0, "포장": 1, "고장": 2, "누수": 2, "가격": 3}


class _KeywordEmbedder:
    model = "bge-m3"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.01] * EMBEDDING_DIMENSIONS
            for word, axis in AXES.items():
                if word in text:
                    vector[axis] += 1.0
            vectors.append(vector)
        return vectors


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quick_answer, "_aspect_vectors", {})
    monkeypatch.setattr(quick_answer, "_faq_vectors", [])
    monkeypatch.setattr(quick_answer, "OllamaEmbedder", lambda **_: _KeywordEmbedder())


def test_question_is_linked_to_matching_aspects_with_db_counts() -> None:
    with SessionLocal() as session:
        result = QuickAnswerService(session).answer(PRODUCT, "  배송이   너무 늦게 왔어요 ")
    assert result["question"] == "배송이 너무 늦게 왔어요"
    assert result["aspects"][0]["detail_label"] == "shipping"
    assert result["analyzed_reviews"] == 12
    assert result["is_small_sample"] is True
    assert "분석한 리뷰 12건" in result["answer_text"]
    # 수치는 DB 집계값 그대로(언급 수 ≥ 좋아요 + 아쉬워요 중 큰 값)
    for aspect in result["aspects"]:
        assert aspect["mention_count"] >= max(aspect["positive_count"], aspect["negative_count"])


def test_faq_like_question_returns_stored_faq_only_when_available() -> None:
    with SessionLocal() as session:
        result = QuickAnswerService(session).answer(PRODUCT, "배송이나 포장 문제는 없나요?")
    # fixture 상품에는 저장된 FAQ가 없으므로 FAQ 답은 붙지 않습니다.
    assert result["matched_faq"] is None
    assert {item["detail_label"] for item in result["aspects"]} <= {"shipping", "packaging"}


def test_quick_answer_api_goes_through_mcp_and_is_fast(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/products/{PRODUCT}/quick-answer", json={"question": "고장이 잦나요?"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_calls"][0]["tool"] == "quick_answer"
    assert payload["tool_calls"][0]["transport"] == "mcp_memory"
    assert payload["latency_ms"] < 5000
    assert payload["aspects"][0]["detail_label"] == "reliability"


def test_quick_answer_errors(client: TestClient) -> None:
    missing = client.post("/api/v1/products/nope/quick-answer", json={"question": "괜찮나요?"})
    assert missing.status_code == 404
    short = client.post(f"/api/v1/products/{PRODUCT}/quick-answer", json={"question": "a"})
    assert short.status_code == 422
