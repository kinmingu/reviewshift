"""LangGraph 챗봇이 ReviewShift MCP 서버의 도구를 MCP 프로토콜로 호출하는 클라이언트.

- mcp_stdio(기본): MCP 서버를 별도 프로세스(python -m backend.app.mcp_server)로 띄워 표준 입출력으로 연결
- mcp_memory: 같은 프로세스 안에서 MCP 프로토콜로 연결(테스트·진단용)
질문 하나마다 연결을 한 번 열고, 그 안에서 필요한 도구를 차례로 호출합니다.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

from mcp import Client, StdioServerParameters

from backend.app.core.config import PROJECT_ROOT

TRANSPORTS = ("mcp_stdio", "mcp_memory")


class McpUnavailableError(RuntimeError):
    """MCP 서버를 띄우거나 연결할 수 없음(연결 단계 오류)."""


# MCP 도구 호출 결과 한 건(성공 여부, 데이터, 오류, 걸린 시간).
@dataclass(frozen=True)
class McpToolResult:
    tool: str
    arguments: dict[str, Any]
    ok: bool
    data: dict[str, Any] | None
    error: str | None
    duration_ms: int


# MCP 응답에서 JSON 데이터를 꺼냅니다.
def _payload(result: Any) -> dict[str, Any]:
    if result.structured_content:
        content = result.structured_content
        return content.get("result", content)
    return json.loads(result.content[0].text)


# MCP 오류 응답에서 사람이 읽을 메시지를 꺼냅니다.
def _error_text(result: Any) -> str:
    texts = [getattr(item, "text", "") for item in result.content or []]
    return " ".join(text for text in texts if text)[:500] or "알 수 없는 도구 오류"


# [MCP 클라이언트] 우리 MCP 도구 서버에 연결해 도구를 호출합니다(stdio 별도 프로세스 또는 같은 프로세스).
class McpReviewTools:
    def __init__(self, transport: str = "mcp_stdio", timeout_seconds: float = 120) -> None:
        if transport not in TRANSPORTS:
            raise ValueError(f"지원하지 않는 MCP 연결 방식입니다: {transport}")
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    # 연결 방식에 맞는 MCP 서버 대상(같은 프로세스 객체 또는 별도 프로세스 실행 명령)을 고릅니다.
    def _server(self) -> Any:
        if self.transport == "mcp_memory":
            from backend.app.mcp_server import server

            return server
        return StdioServerParameters(
            command=sys.executable,
            args=["-m", "backend.app.mcp_server"],
            cwd=str(PROJECT_ROOT),
            # 테스트에서는 DATABASE_URL이 테스트 DB로 바뀌어 있으므로 그대로 넘깁니다.
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

    # === [도구 호출] 한 번의 연결 안에서 여러 도구를 순서대로 부릅니다 ===
    def call_tools(self, calls: list[tuple[str, dict[str, Any]]]) -> list[McpToolResult]:
        try:
            return asyncio.run(asyncio.wait_for(self._call_all(calls), self.timeout_seconds))
        except TimeoutError as exc:
            raise McpUnavailableError(f"MCP 도구 응답 시간 초과({self.timeout_seconds}초)") from exc
        except McpUnavailableError:
            raise
        except Exception as exc:  # 서버 실행 실패·연결 끊김 등
            raise McpUnavailableError(f"MCP 서버 연결 실패: {type(exc).__name__}: {exc}") from exc

    # MCP 세션 하나를 열어 여러 도구를 차례로 호출하고 결과를 모읍니다.
    async def _call_all(self, calls: list[tuple[str, dict[str, Any]]]) -> list[McpToolResult]:
        results: list[McpToolResult] = []
        async with Client(self._server(), read_timeout_seconds=self.timeout_seconds) as client:
            for name, arguments in calls:
                started = time.perf_counter()
                result = await client.call_tool(name, arguments)
                elapsed = round((time.perf_counter() - started) * 1000)
                if result.is_error:
                    results.append(
                        McpToolResult(name, arguments, False, None, _error_text(result), elapsed)
                    )
                else:
                    results.append(
                        McpToolResult(name, arguments, True, _payload(result), None, elapsed)
                    )
        return results
