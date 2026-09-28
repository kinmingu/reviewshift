"""챗봇 답변 저장소: 미리 생성한 자주 묻는 질문(FAQ) 답변 + 한 번 답한 질문 캐시.

- 저장하는 답은 Agent 검증(인용 ID·수치·내부 용어·반복)을 통과한 답뿐입니다.
- 답을 만든 시점의 분석 버전·분석 성공 건수를 함께 저장합니다. 지금과 다르면 is_stale=True이며,
  자유 질문 캐시는 낡은 답을 쓰지 않고 새로 만듭니다(FAQ는 표시하되 낡았다고 알립니다).
- 이전 대화가 있는 후속 질문은 문맥에 따라 답이 달라지므로 캐시를 쓰지 않습니다.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.app.models import AgentAnswer
from backend.app.schemas.catalog import (
    AgentAnswerResponse,
    AgentCitation,
    AgentToolCall,
    FaqItem,
    FaqResponse,
)
from backend.app.services.catalog import CatalogService, ProductNotFoundError
from backend.app.services.review_agent import AGENT_PROMPT_VERSION, ReviewQuestionAgent

# 분석 수가 이만큼 이하로 바뀌면 저장 답을 그대로 씁니다.
STALE_RATIO = 0.05
STALE_MIN_COUNT = 2

# === [자주 묻는 질문] 상품마다 미리 답을 만들어 두는 질문(첫 번째는 리포트 상단 요약) ===
FAQ_QUESTIONS: tuple[tuple[str, str, str], ...] = (
    ("summary", "AI 리뷰 요약", "이 상품 리뷰를 종합하면 어떤가요? 좋은 점과 아쉬운 점을 알려 주세요."),
    ("durability", "고장·불량", "금방 고장 나거나 불량이 많은가요?"),
    ("shipping", "배송·포장", "배송이나 포장 문제는 없나요?"),
    ("value", "가격 대비", "가격 대비 괜찮은가요?"),
    ("usability", "사용 편의", "사용하거나 설치하기 편한가요?"),
    ("safety", "안전·주의", "안전 문제나 주의할 점은 없나요?"),
)


def question_key(question: str) -> str:
    """띄어쓰기·대소문자·끝 문장부호만 다른 질문은 같은 질문으로 봅니다."""
    normalized = " ".join(question.lower().split())
    return re.sub(r"[\s?!.~。？！]+$", "", normalized)[:600]


# 상품 × 질문 키 × 프롬프트 버전으로 저장 답의 고유 ID를 만듭니다.
def _answer_id(product_id: str, key: str, prompt_version: str) -> str:
    digest = hashlib.sha256(f"{product_id}|{key}|{prompt_version}".encode()).hexdigest()
    return f"answer:{digest}"


# 답을 만들 당시의 분석 상태(분석 버전, 분석된 리뷰 수). 오래된 답을 가려내는 기준.
@dataclass(frozen=True)
class AnalysisSnapshot:
    version: str
    analyzed_count: int


# [답 저장소] 챗봇 답을 DB에 저장하고, 분석이 바뀌었으면 '오래된 답'으로 판단합니다.
class AnswerStore:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.catalog = CatalogService(session)

    # === [현재 분석 상태] 저장 답이 낡았는지 판단하는 기준 ===
    def snapshot(self, product_id: str) -> AnalysisSnapshot:
        product = self.catalog.products.get(product_id)
        if product is None:
            raise ProductNotFoundError(product_id)
        run = self.catalog._active_run(product)
        if run is None:
            return AnalysisSnapshot("not-analyzed", 0)
        return AnalysisSnapshot(run.id, self.catalog.insights.succeeded_count(product_id, run.id))

    # 같은 상품·같은 질문으로 저장된 답을 찾습니다.
    def get(self, product_id: str, question: str) -> AgentAnswer | None:
        return self.session.scalar(
            select(AgentAnswer).where(
                AgentAnswer.product_id == product_id,
                AgentAnswer.question_key == question_key(question),
                AgentAnswer.prompt_version == AGENT_PROMPT_VERSION,
            )
        )

    @staticmethod
    def is_stale(row: AgentAnswer, snapshot: AnalysisSnapshot) -> bool:
        """분석 버전이 바뀌었거나 분석 수가 5%(최소 2건)를 넘게 달라졌으면 낡은 답입니다.

        1~2건의 재분류마다 답 6개를 다시 만들지 않도록 작은 변화는 허용하고, 화면에는 답을 만든
        시점의 분석 건수를 그대로 표시합니다.
        """
        if row.analysis_version != snapshot.version:
            return True
        tolerance = max(STALE_MIN_COUNT, math.ceil(row.analyzed_count * STALE_RATIO))
        return abs(snapshot.analyzed_count - row.analyzed_count) > tolerance

    # === [저장] 검증을 통과한 답만 같은 질문 키로 덮어씁니다 ===
    def save(
        self,
        product_id: str,
        result: AgentAnswerResponse,
        snapshot: AnalysisSnapshot,
        faq_key: str | None = None,
    ) -> None:
        if result.status != "answered" or not result.answer:
            return
        key = question_key(result.question)
        values = {
            "id": _answer_id(product_id, key, result.prompt_version),
            "product_id": product_id,
            "kind": "faq" if faq_key else "cache",
            "faq_key": faq_key,
            "question_key": key,
            "question": result.question,
            "answer": result.answer,
            "citations_json": [item.model_dump() for item in result.citations],
            "tool_calls_json": [item.model_dump() for item in result.tool_calls],
            "generation_attempts": result.generation_attempts,
            "is_provisional": result.is_provisional,
            "model": result.model,
            "prompt_version": result.prompt_version,
            "analysis_version": snapshot.version,
            "analyzed_count": snapshot.analyzed_count,
            "latency_ms": result.latency_ms,
        }
        statement = insert(AgentAnswer).values(**values)
        updates = {k: v for k, v in values.items() if k not in ("id", "product_id", "question_key")}
        # FAQ로 만든 답은 이후 같은 질문의 캐시 저장으로 kind가 바뀌지 않게 합니다.
        if not faq_key:
            updates.pop("kind")
            updates.pop("faq_key")
        statement = statement.on_conflict_do_update(
            constraint="uq_agent_answers_question",
            set_={**updates, "created_at": statement.excluded.created_at},
        )
        self.session.execute(statement)
        self.session.commit()

    # 저장된 답(DB 행)을 API 응답 형식으로 바꿉니다(오래됐는지 표시 포함).
    @staticmethod
    def to_response(row: AgentAnswer, snapshot: AnalysisSnapshot) -> AgentAnswerResponse:
        return AgentAnswerResponse(
            product_id=row.product_id,
            question=row.question,
            search_query=row.question,
            status="answered",
            answer=row.answer,
            citations=[AgentCitation(**item) for item in row.citations_json],
            tool_calls=[AgentToolCall(**item) for item in row.tool_calls_json],
            generation_attempts=row.generation_attempts,
            failure_reason=None,
            notice=None,
            is_provisional=row.is_provisional,
            model=row.model,
            prompt_version=row.prompt_version,
            latency_ms=row.latency_ms,
            cached=True,
            generated_at=row.created_at,
            analyzed_count=row.analyzed_count,
            is_stale=AnswerStore.is_stale(row, snapshot),
        )

    # === [FAQ 목록] 미리 만든 답(없으면 null)과 현재 분석 상태 ===
    def faq(self, product_id: str) -> FaqResponse:
        snapshot = self.snapshot(product_id)
        items = []
        for key, label, question in FAQ_QUESTIONS:
            row = self.get(product_id, question)
            items.append(
                FaqItem(
                    key=key,
                    label=label,
                    question=question,
                    answer=self.to_response(row, snapshot) if row else None,
                )
            )
        return FaqResponse(
            product_id=product_id,
            analysis_version=snapshot.version,
            current_analyzed_count=snapshot.analyzed_count,
            items=items,
        )


# === [챗봇 진입점] 캐시 확인 → 없거나 낡았으면 Agent 실행 → 검증 통과 답 저장 ===
class ChatService:
    def __init__(self, session: Session, agent: ReviewQuestionAgent | None = None) -> None:
        self.session = session
        self.store = AnswerStore(session)
        self._agent = agent

    # AI 에이전트는 실제로 필요할 때 처음 만듭니다(저장 답만 쓰는 경우 모델 준비를 건너뜀).
    @property
    def agent(self) -> ReviewQuestionAgent:
        if self._agent is None:
            self._agent = ReviewQuestionAgent(self.session)
        return self._agent

    # 질문에 답합니다: 대화 첫 질문이고 최신 저장 답이 있으면 그대로, 아니면 AI 에이전트로 새로 만들어 저장합니다.
    def ask(
        self, product_id: str, question: str, history: list[dict[str, str]] | None = None
    ) -> AgentAnswerResponse:
        snapshot = self.store.snapshot(product_id)
        if not history:
            row = self.store.get(product_id, question)
            if row is not None and not self.store.is_stale(row, snapshot):
                return self.store.to_response(row, snapshot)
        result = self.agent.ask(product_id, question, history)
        if not history:
            faq_key = next(
                (key for key, _, text in FAQ_QUESTIONS if question_key(text) == question_key(question)),
                None,
            )
            self.store.save(product_id, result, snapshot, faq_key=faq_key)
        result.analyzed_count = snapshot.analyzed_count
        return result

