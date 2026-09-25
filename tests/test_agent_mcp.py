"""LangGraph 챗봇이 도구를 MCP 프로토콜로 호출하는지: 인메모리·stdio 연결, 검색 실패·연결 실패 처리.

LLM은 가짜 응답을 쓰고, 리뷰 검색 임베딩은 가짜 벡터(인메모리) 또는 실제 서버 프로세스(stdio)를 씁니다.
"""

import json

import pytest

from backend.app.core.database import SessionLocal
from backend.app.models.domain import EMBEDDING_DIMENSIONS
from backend.app.services import review_search
from backend.app.services.embeddings import EmbeddingError
from backend.app.services.mcp_tools import McpReviewTools, McpUnavailableError
from backend.app.services.review_agent import AgentUnavailableError, ReviewQuestionAgent

PRODUCT = "fixture-prod-coffee"


def _llm(messages: list) -> str:
    # 수치·인용 없이 답해 검증을 통과하는 고정 응답
    return json.dumps({"answer": "다른 구매자 리뷰를 참고했어요.", "cited_review_ids": []})


class _FakeEmbedder:
    model = "bge-m3"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise EmbeddingError("timeout")
        return [[1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1) for _ in texts]


def _agent(transport: str) -> ReviewQuestionAgent:
    return ReviewQuestionAgent(SessionLocal(), llm_call=_llm, tool_transport=transport)


def test_agent_calls_report_and_search_tools_over_in_memory_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(review_search, "OllamaEmbedder", lambda **_: _FakeEmbedder())
    result = _agent("mcp_memory").ask(PRODUCT, "누수 문제 있나요?")
    assert result.status == "answered"
    assert [(call.tool, call.ok, call.transport) for call in result.tool_calls] == [
        ("get_product_report", True, "mcp_memory"),
        ("search_reviews", True, "mcp_memory"),
    ]
    # MCP 도구에도 상품과 저장 월이 명시적으로 전달됩니다.
    assert result.tool_calls[1].arguments["months"] == ["2025-01", "2025-02"]


def test_search_tool_error_over_mcp_falls_back_to_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(review_search, "OllamaEmbedder", lambda **_: _FakeEmbedder(fail=True))
    result = _agent("mcp_memory").ask(PRODUCT, "누수 문제 있나요?")
    assert result.status == "answered"
    assert result.tool_calls[1].ok is False
    assert "임베딩" in result.tool_calls[1].summary
    assert result.notice and "집계 수치만" in result.notice


def test_agent_reaches_mcp_server_process_over_stdio() -> None:
    # 실제로 python -m backend.app.mcp_server를 띄워 표준 입출력으로 연결합니다(테스트 DB 사용).
    result = _agent("mcp_stdio").ask(PRODUCT, "누수 문제 있나요?")
    assert result.status == "answered"
    report_call = result.tool_calls[0]
    assert (report_call.tool, report_call.ok, report_call.transport) == (
        "get_product_report",
        True,
        "mcp_stdio",
    )
    assert "리뷰 12건" in report_call.summary
    # 검색은 로컬 bge-m3 사용 가능 여부에 따라 성공하거나, 실패 시 집계만으로 답합니다.
    assert result.tool_calls[1].transport == "mcp_stdio"


def test_mcp_connection_failure_becomes_agent_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(self, calls):
        raise McpUnavailableError("MCP 서버 연결 실패: 테스트")

    monkeypatch.setattr(McpReviewTools, "call_tools", broken)
    with pytest.raises(AgentUnavailableError, match="MCP"):
        _agent("mcp_stdio").ask(PRODUCT, "누수 문제 있나요?")
