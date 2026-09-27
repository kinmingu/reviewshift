"""챗봇 답변 저장: 같은 질문 즉시 응답, 후속 질문은 캐시 미사용, 분석 진행 시 낡은 답 재생성, FAQ 목록.

가짜 Agent로 LLM 없이 테스트 DB의 fixture 상품만 사용합니다.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update

from backend.app.core.database import SessionLocal
from backend.app.models import AgentAnswer
from backend.app.schemas.catalog import AgentAnswerResponse, AgentCitation
from backend.app.services import answer_store
from backend.app.services.answer_store import FAQ_QUESTIONS, question_key
from backend.app.services.review_agent import AGENT_PROMPT_VERSION
from scripts import generate_faq_answers

PRODUCT = "fixture-prod-coffee"


class _CountingAgent:
    calls: list[tuple[str, list | None]] = []
    status = "answered"

    def __init__(self, *_: object, **__: object) -> None:
        pass

    def ask(self, product_id: str, question: str, history=None) -> AgentAnswerResponse:
        _CountingAgent.calls.append((question, history))
        answered = _CountingAgent.status == "answered"
        return AgentAnswerResponse(
            product_id=product_id,
            question=" ".join(question.split()),
            search_query=question,
            status=_CountingAgent.status,
            answer=f"답변 {len(_CountingAgent.calls)}" if answered else None,
            citations=[AgentCitation(review_id="r1", rating=2, date="2025-02-01", excerpt="leak")]
            if answered
            else [],
            tool_calls=[],
            generation_attempts=1,
            failure_reason=None if answered else "검증 실패",
            notice=None,
            is_provisional=False,
            model="fake-model",
            prompt_version=AGENT_PROMPT_VERSION,
            latency_ms=123_000,
        )


@pytest.fixture(autouse=True)
def fake_agent(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    _CountingAgent.calls = []
    _CountingAgent.status = "answered"
    monkeypatch.setattr(answer_store, "ReviewQuestionAgent", _CountingAgent)
    monkeypatch.setattr(generate_faq_answers, "ReviewQuestionAgent", _CountingAgent)
    yield
    with SessionLocal() as session:
        session.execute(delete(AgentAnswer).where(AgentAnswer.product_id == PRODUCT))
        session.commit()


def _ask(client: TestClient, question: str, history: list | None = None) -> dict:
    response = client.post(
        f"/api/v1/products/{PRODUCT}/questions",
        json={"question": question, "history": history or []},
    )
    assert response.status_code == 200
    return response.json()


def test_same_question_is_served_from_store(client: TestClient) -> None:
    first = _ask(client, "누수 문제 있나요?")
    second = _ask(client, "  누수   문제 있나요  ")  # 띄어쓰기·물음표만 다름
    assert first["cached"] is False
    assert second["cached"] is True
    assert second["answer"] == first["answer"]
    assert second["generated_at"] is not None
    assert second["analyzed_count"] == 12
    assert second["is_stale"] is False
    assert len(_CountingAgent.calls) == 1  # 두 번째는 LLM을 부르지 않음


def test_follow_up_questions_bypass_store(client: TestClient) -> None:
    _ask(client, "누수 문제 있나요?")
    history = [{"role": "user", "content": "이전 질문"}]
    follow = _ask(client, "누수 문제 있나요?", history)
    assert follow["cached"] is False
    assert len(_CountingAgent.calls) == 2
    # 후속 질문 답은 저장하지 않습니다(같은 질문 키는 첫 답 그대로).
    with SessionLocal() as session:
        rows = session.query(AgentAnswer).filter(AgentAnswer.product_id == PRODUCT).all()
    assert [row.answer for row in rows] == ["답변 1"]


def test_stale_answer_is_regenerated_after_analysis_progress(client: TestClient) -> None:
    _ask(client, "누수 문제 있나요?")
    with SessionLocal() as session:
        session.execute(
            update(AgentAnswer)
            .where(AgentAnswer.product_id == PRODUCT)
            .values(analyzed_count=5)  # 답을 만든 뒤 분석이 더 진행된 상황
        )
        session.commit()
    again = _ask(client, "누수 문제 있나요?")
    assert again["cached"] is False
    assert again["answer"] == "답변 2"
    assert len(_CountingAgent.calls) == 2


def test_failed_answers_are_not_stored(client: TestClient) -> None:
    _CountingAgent.status = "failed"
    _ask(client, "누수 문제 있나요?")
    _ask(client, "누수 문제 있나요?")
    assert len(_CountingAgent.calls) == 2


def test_faq_generation_and_listing(client: TestClient) -> None:
    empty = client.get(f"/api/v1/products/{PRODUCT}/faq").json()
    assert [item["key"] for item in empty["items"]] == [key for key, _, _ in FAQ_QUESTIONS]
    assert all(item["answer"] is None for item in empty["items"])

    counts = generate_faq_answers.generate([PRODUCT], force=False, only={"summary", "shipping"})
    assert counts["generated"] == 2
    rerun = generate_faq_answers.generate([PRODUCT], force=False, only={"summary"})
    assert rerun["skipped_fresh"] == 1  # 분석 상태가 그대로면 다시 만들지 않음

    listed = client.get(f"/api/v1/products/{PRODUCT}/faq").json()
    by_key = {item["key"]: item for item in listed["items"]}
    assert by_key["summary"]["answer"]["cached"] is True
    assert by_key["summary"]["answer"]["is_stale"] is False
    assert by_key["durability"]["answer"] is None
    assert listed["current_analyzed_count"] == 12

    # FAQ 질문을 챗봇에 그대로 입력해도 저장된 답이 바로 나옵니다.
    summary_question = next(text for key, _, text in FAQ_QUESTIONS if key == "summary")
    assert _ask(client, summary_question)["cached"] is True
    with SessionLocal() as session:
        row = (
            session.query(AgentAnswer)
            .filter(AgentAnswer.question_key == question_key(summary_question))
            .one()
        )
    assert (row.kind, row.faq_key) == ("faq", "summary")


def test_faq_for_missing_product_returns_404(client: TestClient) -> None:
    assert client.get("/api/v1/products/nope/faq").status_code == 404


def test_small_analysis_change_keeps_stored_answer(client: TestClient) -> None:
    _ask(client, "누수 문제 있나요?")
    with SessionLocal() as session:
        session.execute(
            update(AgentAnswer)
            .where(AgentAnswer.product_id == PRODUCT)
            .values(analyzed_count=11)  # 12건 중 1건 차이: 허용 범위(5% 또는 2건)
        )
        session.commit()
    again = _ask(client, "누수 문제 있나요?")
    assert again["cached"] is True
    assert again["is_stale"] is False
    assert again["analyzed_count"] == 11  # 화면에는 답을 만든 시점의 건수를 그대로 표시
    assert len(_CountingAgent.calls) == 1
