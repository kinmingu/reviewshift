"""MCP 서버: 도구 목록·읽기 전용 표시, 도구 결과, 입력 오류, 없는 상품 처리(테스트 DB fixture 사용)."""

import asyncio
import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from backend.app import mcp_server
from backend.app.services import review_search
from backend.app.services.answer_store import FAQ_QUESTIONS

PRODUCT = "fixture-prod-coffee"


def _call(name: str, arguments: dict):
    return asyncio.run(mcp_server.server.call_tool(name, arguments))


def _payload(result) -> dict:
    if result.structured_content:
        content = result.structured_content
        return content.get("result", content)
    return json.loads(result.content[0].text)


def _error(name: str, arguments: dict) -> str:
    """사용자에게 보여야 하는 입력 오류는 ToolError(프로토콜에서는 isError 결과)로 올라옵니다."""
    with pytest.raises(ToolError) as caught:
        _call(name, arguments)
    return str(caught.value)


def test_tools_are_listed_and_read_only() -> None:
    tools = {tool.name: tool for tool in asyncio.run(mcp_server.server.list_tools())}
    assert set(tools) == {
        "list_products",
        "get_product_report",
        "compare_months",
        "search_reviews",
        "get_faq_answers",
        "quick_answer",
    }
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools.values())
    assert "months" in tools["search_reviews"].input_schema["required"]


def test_report_and_comparison_tools_return_sql_aggregates() -> None:
    report = _payload(_call("get_product_report", {"product_id": PRODUCT}))
    assert report["review_count"] == 12
    assert report["analysis"]["status"] == "complete"

    comparison = _payload(
        _call(
            "compare_months",
            {"product_id": PRODUCT, "baseline_month": "2025-01", "target_month": "2025-02"},
        )
    )
    assert comparison["coverage"]["target_total"] == 6
    assert all(len(item["evidence_review_ids"]) <= 5 for item in comparison["issues"])

    faq = _payload(_call("get_faq_answers", {"product_id": PRODUCT}))
    assert len(faq["items"]) == len(FAQ_QUESTIONS)


def test_errors_are_reported_as_tool_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "list_products" in _error("get_product_report", {"product_id": "nope"})
    assert "months" in _error(
        "search_reviews", {"product_id": PRODUCT, "query": "leak", "months": []}
    )
    assert "카테고리" in _error("list_products", {"category": "Groceries"})
    assert "월 입력 오류" in _error(
        "compare_months",
        {"product_id": PRODUCT, "baseline_month": "2025-02", "target_month": "2025-01"},
    )

    class _DownEmbedder:
        model = "bge-m3"

        def embed(self, texts):
            from backend.app.services.embeddings import EmbeddingError

            raise EmbeddingError("timeout")

    monkeypatch.setattr(review_search, "OllamaEmbedder", lambda **_: _DownEmbedder())
    assert "임베딩" in _error(
        "search_reviews", {"product_id": PRODUCT, "query": "leak", "months": ["2025-02"]}
    )
