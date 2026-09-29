"""빠른 AI 답변(요약본 RAG + 스트리밍): 요약본 구성, 인용 번호·수치 검증, 재생성, NDJSON API, 카드 분석 상태."""

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.models.domain import EMBEDDING_DIMENSIONS
from backend.app.services import fast_answer, quick_answer
from backend.app.services.fast_answer import FastAnswerService, build_digest, verify
from backend.app.services.mcp_tools import McpToolResult

PRODUCT = "fixture-prod-coffee"
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


def _fake_stream(*answers: str):
    """정해 둔 답을 두 글자씩 흘려보내는 가짜 LLM(호출마다 다음 답)."""
    calls = []

    def stream(messages, **_options):
        calls.append(messages)
        text = answers[min(len(calls), len(answers)) - 1]
        for start in range(0, len(text), 2):
            yield text[start:start + 2], None
        yield "", {"prompt_tokens": 100, "prompt_ms": 1, "output_tokens": 10, "output_ms": 1}

    stream.calls = calls
    return stream


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quick_answer, "_aspect_vectors", {})
    monkeypatch.setattr(quick_answer, "_faq_vectors", [])
    monkeypatch.setattr(quick_answer, "OllamaEmbedder", lambda **_: _KeywordEmbedder())


QUICK = {
    "aspects": [{
        "name_ko": "신뢰성 · 고장", "mention_count": 10, "positive_count": 2, "negative_count": 8,
        "examples": [
            {"review_id": "r1", "polarity": "negative", "rating": 1, "date": "2022-01-02", "evidence": "broke in a week"},
            {"review_id": "r2", "polarity": "positive", "rating": 5, "date": "2022-01-03", "evidence": "still works"},
        ],
    }],
    "related_reviews": [
        {"review_id": "r1", "rating": 1, "date": "2022-01-02", "title": "Bad", "text": "broke in a week"},
        {"review_id": "r3", "rating": 2, "date": "2022-01-04", "title": "Meh", "text": "stopped working"},
    ],
}
REPORT = {
    "product_id": "p", "positive_review_share": 0.5, "negative_review_share": 0.25,
    "analysis": {"succeeded": 40, "status": "complete"},
}


def test_digest_uses_server_counts_and_numbers_sources_once() -> None:
    digest, sources, allowed = build_digest(QUICK, REPORT)
    # 리뷰 ID가 겹치는 근거(r1)는 한 번만 번호를 받습니다.
    assert [source["review_id"] for source in sources] == ["r1", "r2", "r3"]
    assert "[3]" in digest and "[4]" not in digest
    # % 값은 모두 서버가 계산(40건 중 8건 = 20%, 2건 = 5%, 전체 50%·25%)
    assert set(allowed) == {50.0, 25.0, 20.0, 5.0}
    assert "언급 10건" in digest


def test_small_sample_digest_has_no_percentages() -> None:
    small = {**REPORT, "analysis": {"succeeded": 12, "status": "complete"}}
    digest, _, allowed = build_digest(QUICK, small)
    assert allowed == []
    assert "%" not in digest.split("질문과 관련된 항목")[1]


def test_verify_rejects_unknown_citation_number_percent_and_internal_terms() -> None:
    _, sources, allowed = build_digest(QUICK, REPORT)
    markers, problems = verify("고장 리뷰가 20%예요 [1][3].", sources, allowed, None)
    assert markers == [1, 3] and problems == []
    _, problems = verify("고장이 33%예요 [9]. 자료에 따르면 [자료]", sources, allowed, None)
    joined = " ".join(problems)
    assert "없는 근거 번호" in joined and "없는 수치" in joined and "내부 용어" in joined


class _FakeTools:
    """MCP 도구 대신 정해 둔 즉시 답·리포트를 돌려줍니다(인용 번호 대응을 확인하기 위해)."""

    def call_tools(self, calls):
        return [
            McpToolResult(tool=name, arguments=args, ok=True, data=data, error=None, duration_ms=1)
            for (name, args), data in zip(calls, (QUICK, REPORT), strict=True)
        ]


def _service(stream) -> FastAnswerService:
    service = FastAnswerService(stream_call=stream)
    service.tools = _FakeTools()
    return service


def test_stream_emits_tokens_then_verified_answer_with_cited_reviews() -> None:
    stream = _fake_stream("고장 리뷰는 20%예요 [3].")
    events = list(_service(stream).stream("p", "고장이 잦나요?", product_name="커피"))
    types = [event["type"] for event in events]
    assert types[0] == "status" and "token" in types and types[-1] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "token") == "고장 리뷰는 20%예요 [3]."
    result = events[-1]["result"]
    assert result["status"] == "answered"
    assert result["prompt_version"] == fast_answer.FAST_PROMPT_VERSION
    # [3]은 요약본의 세 번째 근거(r3) 리뷰로 연결됩니다.
    assert [c["review_id"] for c in result["citations"]] == ["r3"]
    assert result["citations"][0]["excerpt"].startswith("[3]")
    # 고정 지시문이 항상 첫 메시지(프롬프트 캐시 조건)
    assert stream.calls[0][0] == {"role": "system", "content": fast_answer.FAST_SYSTEM_PROMPT}


def test_stream_retries_once_after_verification_failure_then_hides_bad_answer() -> None:
    retried = _fake_stream("고장률은 77%입니다 [1].", "고장 리뷰가 있어요 [1].")
    events = list(_service(retried).stream("p", "고장이 잦나요?"))
    assert any(event["type"] == "retry" for event in events)
    assert events[-1]["result"]["status"] == "answered"
    assert events[-1]["result"]["generation_attempts"] == 2
    assert "거부" in retried.calls[1][1]["content"]

    always_bad = _fake_stream("고장률은 77%입니다 [1].")
    result = list(_service(always_bad).stream("p", "고장이 잦나요?"))[-1]["result"]
    assert result["status"] == "failed" and result["answer"] is None and result["citations"] == []


def test_stream_collects_evidence_through_mcp_on_fixture_product() -> None:
    # fixture 상품에는 이 질문의 근거 문장이 없으므로 [1]을 인용하면 거부되고, 인용 없는 답은 통과합니다.
    result = list(
        FastAnswerService(stream_call=_fake_stream("분석한 리뷰에서는 관련 언급을 찾지 못했어요."))
        .stream(PRODUCT, "고장이 잦나요?")
    )[-1]["result"]
    assert result["status"] == "answered"
    assert [call["tool"] for call in result["tool_calls"]] == ["quick_answer", "get_product_report"]
    assert all(call["transport"] == "mcp_memory" for call in result["tool_calls"])
    cited = list(FastAnswerService(stream_call=_fake_stream("리뷰가 있어요 [1].")).stream(PRODUCT, "고장이 잦나요?"))
    assert cited[-1]["result"]["status"] == "failed"


def test_stream_api_returns_ndjson_events(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fast_answer, "ollama_stream", _fake_stream("분석한 리뷰에서는 관련 언급을 찾지 못했어요."))
    response = client.post(f"/api/v1/products/{PRODUCT}/questions/stream", json={"question": "고장이 잦나요?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert events[-1]["type"] == "done" and events[-1]["result"]["status"] == "answered"

    assert client.post("/api/v1/products/nope/questions/stream", json={"question": "괜찮나요?"}).status_code == 404
    assert client.post(f"/api/v1/products/{PRODUCT}/questions/stream", json={"question": "a"}).status_code == 422


def test_cancelled_stream_does_not_start_generation() -> None:
    stream = _fake_stream("고장 리뷰가 있어요 [1].")
    service = _service(stream)
    service.cancel()  # 사용자가 새 질문을 보내 취소한 상태
    events = list(service.stream("p", "고장이 잦나요?"))
    assert stream.calls == []
    assert all(event["type"] == "status" for event in events)


def test_stream_api_reports_unexpected_errors_instead_of_ending_silently(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(messages, **_options):
        raise KeyError("boom")
        yield  # pragma: no cover

    monkeypatch.setattr(fast_answer, "ollama_stream", broken)
    response = client.post(f"/api/v1/products/{PRODUCT}/questions/stream", json={"question": "고장이 잦나요?"})
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert events[-1]["type"] == "error" and "KeyError" in events[-1]["message"]


def test_product_cards_carry_server_analysis_status(client: TestClient) -> None:
    items = client.get("/api/v1/products", params={"source_mode": "fixture"}).json()["items"]
    assert items and all(
        item["analysis_status"] in {"not_started", "in_progress", "complete", "partial_failure"}
        for item in items
    )
