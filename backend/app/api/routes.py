"""API 주소(라우트) 모음: 화면(React·Streamlit)이 호출하는 모든 HTTP 엔드포인트.

각 함수는 요청 값을 검사하고 서비스 계층(services/)을 호출한 뒤, 오류를 HTTP 상태 코드(404·422·503)로 바꿉니다.
실제 계산·검색·AI 로직은 여기에 두지 않습니다.
"""

import asyncio
import json
import logging
import threading
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.database import SessionLocal, get_db
from backend.app.schemas.catalog import (
    AgentAnswerResponse,
    AgentQuestionRequest,
    AnomalyReport,
    CategoryListResponse,
    ComparisonResponse,
    EvaluationItemResponse,
    EvaluationProgressResponse,
    EvaluationSaveRequest,
    FaqResponse,
    HealthResponse,
    ProductDetail,
    ProductInsightResponse,
    ProductListResponse,
    ReviewListResponse,
    ReviewSearchResponse,
    TranslationResponse,
)
from backend.app.services.anomaly import cached_report
from backend.app.services.answer_store import AnalysisSnapshot, AnswerStore, ChatService
from backend.app.services.catalog import (
    AnalysisRunUnavailableError,
    CatalogService,
    ProductNotFoundError,
)
from backend.app.services.embeddings import EmbeddingError
from backend.app.services.fast_answer import FastAnswerService
from backend.app.services.human_evaluation import (
    EvaluationNotFoundError,
    EvaluationValidationError,
    HumanEvaluationService,
)
from backend.app.services.mcp_tools import McpReviewTools, McpUnavailableError
from backend.app.services.review_agent import AgentUnavailableError
from backend.app.services.review_search import ReviewSearchService
from backend.app.services.review_translation import TranslationError

router = APIRouter()
logger = logging.getLogger(__name__)
DbSession = Annotated[Session, Depends(get_db)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
Month = Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
SourceModeParam = Annotated[str, Query(pattern=r"^(fixture|real)$")]


# 상품·리뷰 조회 서비스를 만듭니다(요청마다 DB 세션을 받아 생성).
def _service(session: Session) -> CatalogService:
    return CatalogService(session)


# 상품이 없을 때 돌려줄 404 오류를 만듭니다.
def _not_found(product_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"product not found: {product_id}",
    )


# 사람 평가(정답 라벨 작성) 서비스를 만듭니다.
def _evaluation_service(session: Session) -> HumanEvaluationService:
    return HumanEvaluationService(session)


# [사람 평가] 평가 데이터셋의 진행 현황(완료·대기 수).
@router.get(
    "/api/v1/evaluation/datasets/{dataset_id}/progress",
    response_model=EvaluationProgressResponse,
)
def evaluation_progress(dataset_id: str, session: DbSession) -> EvaluationProgressResponse:
    try:
        return _evaluation_service(session).progress(dataset_id)
    except EvaluationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="평가 데이터셋을 찾을 수 없습니다.") from exc


# [사람 평가] 평가 데이터셋의 N번째 리뷰와 AI 예측, 저장된 정답 라벨.
@router.get(
    "/api/v1/evaluation/datasets/{dataset_id}/items/{position}",
    response_model=EvaluationItemResponse,
)
def evaluation_item(
    dataset_id: str, position: int, session: DbSession
) -> EvaluationItemResponse:
    try:
        return _evaluation_service(session).item(dataset_id, position)
    except EvaluationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="평가 항목을 찾을 수 없습니다.") from exc


# [사람 평가] 사람이 매긴 정답 라벨을 저장합니다.
@router.put(
    "/api/v1/evaluation/datasets/{dataset_id}/items/{position}",
    response_model=EvaluationItemResponse,
)
def save_evaluation_item(
    dataset_id: str,
    position: int,
    payload: EvaluationSaveRequest,
    session: DbSession,
) -> EvaluationItemResponse:
    try:
        return _evaluation_service(session).save(dataset_id, position, payload)
    except EvaluationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="평가 항목을 찾을 수 없습니다.") from exc
    except EvaluationValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# [사람 평가] 평가 결과를 CSV로 내려받습니다(엑셀에서 한글이 깨지지 않게 BOM 추가).
@router.get("/api/v1/evaluation/datasets/{dataset_id}/export")
def export_evaluation(dataset_id: str, session: DbSession) -> Response:
    try:
        csv_text = _evaluation_service(session).export_csv(dataset_id)
    except EvaluationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="평가 데이터셋을 찾을 수 없습니다.") from exc
    headers = {
        "Content-Disposition": f'attachment; filename="{dataset_id}.csv"'
    }
    return Response(
        content="\ufeff" + csv_text,
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


# 리뷰 한 건을 한국어로 번역합니다(번역 결과는 DB에 캐시).
@router.post("/api/v1/reviews/{review_id}/translate", response_model=TranslationResponse)
def translate_review(review_id: str, session: DbSession) -> TranslationResponse:
    try:
        return _evaluation_service(session).translate(review_id)
    except EvaluationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="리뷰를 찾을 수 없습니다.") from exc
    except TranslationError as exc:
        raise HTTPException(status_code=503, detail=f"번역 모델 처리 실패: {exc}") from exc


# 서버·DB 상태 확인용(SELECT 1이 되면 ok).
@router.get("/health", response_model=HealthResponse)
def health(session: DbSession) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return HealthResponse(status="degraded", database="unavailable")
    return HealthResponse(status="ok", database="connected")


@router.get("/api/v1/anomalies", response_model=AnomalyReport)
def anomalies(session: DbSession) -> AnomalyReport:
    """모든 상품·모든 인접 두 달의 불만 증가를 통계 검정(Fisher + BH 보정)으로 판정합니다."""
    return cached_report(session)


# 카테고리 목록(실제 데이터 또는 fixture).
@router.get("/api/v1/categories", response_model=CategoryListResponse)
def categories(
    session: DbSession, source_mode: SourceModeParam | None = None
) -> CategoryListResponse:
    selected_mode = source_mode or get_settings().source_mode
    return CategoryListResponse(
        items=_service(session).categories(selected_mode), source_mode=selected_mode
    )


# 상품 목록: 검색어·카테고리로 거르고 페이지 단위로 돌려줍니다.
@router.get("/api/v1/products", response_model=ProductListResponse)
def products(
    session: DbSession,
    query: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=120),
    source_mode: SourceModeParam | None = None,
    page: Page = 1,
    page_size: PageSize = 20,
) -> ProductListResponse:
    service = _service(session)
    selected_mode = source_mode or get_settings().source_mode
    items, total = service.list_products(
        query=query,
        category=category,
        source_mode=selected_mode,
        page=page,
        page_size=page_size,
    )
    return ProductListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        source_mode=selected_mode,
    )


# 상품 상세 정보(월별 리뷰 수·평균 별점 포함).
@router.get("/api/v1/products/{product_id}", response_model=ProductDetail)
def product_detail(product_id: str, session: DbSession) -> ProductDetail:
    try:
        return _service(session).product_detail(product_id)
    except ProductNotFoundError as exc:
        raise _not_found(product_id) from exc


@router.get(
    "/api/v1/products/{product_id}/insights", response_model=ProductInsightResponse
)
def product_insights(product_id: str, session: DbSession) -> ProductInsightResponse:
    """상품 상세의 리뷰 리포트: 별점 분포, 항목별 평가, 주요 불만, 월별 추이, 최근 두 달 변화."""
    try:
        return _service(session).product_insights(product_id)
    except ProductNotFoundError as exc:
        raise _not_found(product_id) from exc


@router.get("/api/v1/products/{product_id}/faq", response_model=FaqResponse)
def product_faq(product_id: str, session: DbSession) -> FaqResponse:
    """미리 생성해 둔 자주 묻는 질문 답변(없으면 answer=null)과 현재 분석 상태."""
    try:
        return AnswerStore(session).faq(product_id)
    except ProductNotFoundError as exc:
        raise _not_found(product_id) from exc


@router.post("/api/v1/products/{product_id}/quick-answer")
def quick_answer(product_id: str, payload: AgentQuestionRequest) -> dict:
    """즉시 답변(LLM 없음): MCP 도구 quick_answer를 같은 프로세스 MCP 연결로 호출합니다."""
    try:
        (result,) = McpReviewTools("mcp_memory", timeout_seconds=60).call_tools(
            [("quick_answer", {"product_id": product_id, "question": payload.question})]
        )
    except McpUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"MCP 도구 호출 실패: {exc}") from exc
    if not result.ok or result.data is None:
        message = result.error or "즉시 답변을 만들지 못했습니다."
        status_code = 404 if "상품을 찾을 수 없습니다" in message else 503
        raise HTTPException(status_code=status_code, detail=message)
    return {**result.data, "tool_calls": [
        {"tool": "quick_answer", "ok": True, "duration_ms": result.duration_ms,
         "summary": f"항목 {len(result.data['aspects'])}개, 관련 리뷰 "
         f"{len(result.data['related_reviews'])}건", "transport": "mcp_memory"}
    ]}


@router.post(
    "/api/v1/products/{product_id}/questions", response_model=AgentAnswerResponse
)
def ask_product_question(
    product_id: str, payload: AgentQuestionRequest, session: DbSession
) -> AgentAnswerResponse:
    """상품 리뷰 질문 Agent. 답변은 도구 수치와 실제 리뷰 인용이 검증된 경우에만 반환합니다."""
    try:
        return ChatService(session).ask(
            product_id,
            payload.question,
            [turn.model_dump() for turn in payload.history],
        )
    except ProductNotFoundError as exc:
        raise _not_found(product_id) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AgentUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"AI 모델 응답 실패: {exc}") from exc


def _save_fast_answer(product_id: str, result: dict, snapshot: AnalysisSnapshot) -> None:
    """작업 스레드에서 호출합니다(요청 세션과 별도 세션). 저장 실패는 답 전달을 막지 않습니다."""
    try:
        with SessionLocal() as session:
            AnswerStore(session).save(
                product_id, AgentAnswerResponse.model_validate(result), snapshot
            )
    except Exception:
        logger.exception("fast answer cache save failed")


@router.post("/api/v1/products/{product_id}/questions/stream")
def ask_product_question_stream(
    product_id: str, payload: AgentQuestionRequest, session: DbSession, request: Request
) -> StreamingResponse:
    """빠른 AI 답변(요약본 RAG): 생성되는 글자를 NDJSON 이벤트로 바로 보내고, 끝나면 검증 결과를 보냅니다.

    이벤트: status · token · retry(검증 실패로 다시 생성, 화면의 글을 지움) · done(result) · error
    """
    product = CatalogService(session).products.get(product_id)
    if product is None:
        raise _not_found(product_id)
    history = [turn.model_dump() for turn in payload.history]
    # 대화 첫 질문이고 같은 질문의 최신 저장 답(FAQ 포함)이 있으면 그대로 돌려줍니다.
    cached = None
    snapshot = None
    if not history:
        store = AnswerStore(session)
        snapshot = store.snapshot(product_id)
        row = store.get(product_id, payload.question)
        if row is not None and not store.is_stale(row, snapshot):
            cached = store.to_response(row, snapshot).model_dump(mode="json")
    name = str(product.metadata_json.get("title_ko") or product.title)

    def line(event: dict) -> str:
        return json.dumps(event, ensure_ascii=False) + "\n"

    async def events():
        if cached is not None:
            yield line({"type": "done", "result": cached, "metrics": {}})
            return
        # 생성은 작업 스레드에서 하고, 여기서는 이벤트를 전달하며 연결이 끊겼는지 지켜봅니다.
        # 끊기면(새 질문·창 닫기) Ollama 연결을 끊어 모델이 다음 질문을 바로 처리하게 합니다.
        service = FastAnswerService()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        def worker() -> None:
            try:
                for event in service.stream(product_id, payload.question, history, name):
                    # 대화 첫 질문의 검증된 답은 저장해 같은 질문을 다시 물으면 바로 답합니다.
                    if event["type"] == "done" and snapshot is not None:
                        _save_fast_answer(product_id, event["result"], snapshot)
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except (AgentUnavailableError, ValueError) as exc:
                if not service.cancelled:
                    loop.call_soon_threadsafe(
                        queue.put_nowait, {"type": "error", "message": str(exc)[:300]}
                    )
            except Exception as exc:  # 취소로 연결을 끊으면 읽기 오류가 날 수 있습니다.
                if not service.cancelled:
                    # 예상 못 한 오류도 스트림이 조용히 끝나지 않게 화면에 알립니다.
                    logger.exception("fast answer stream failed")
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {"type": "error", "message": f"서버 오류: {type(exc).__name__}"},
                    )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=worker, daemon=True).start()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.5)
                except TimeoutError:
                    if await request.is_disconnected():
                        break
                    continue
                if event is None:
                    break
                yield line(event)
        finally:
            service.cancel()

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/v1/products/{product_id}/search", response_model=ReviewSearchResponse)
def search_reviews(
    product_id: str,
    session: DbSession,
    q: str = Query(min_length=1, max_length=300),
    month: list[str] = Query(min_length=1),
    limit: int = Query(default=8, ge=1, le=30),
) -> ReviewSearchResponse:
    """리뷰 의미 검색. 상품과 월(month, 반복 가능)을 반드시 지정해야 합니다."""
    try:
        return ReviewSearchService(session).search(
            product_id=product_id, query=q, months=month, limit=limit
        )
    except ProductNotFoundError as exc:
        raise _not_found(product_id) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=f"임베딩 모델 처리 실패: {exc}") from exc


# 두 달(기준 달 → 비교 달)의 항목별 불만 비율 변화를 비교합니다.
@router.get(
    "/api/v1/products/{product_id}/comparison", response_model=ComparisonResponse
)
def comparison(
    product_id: str,
    session: DbSession,
    target_month: Month,
    baseline_month: Month,
) -> ComparisonResponse:
    try:
        return _service(session).compare(product_id, target_month, baseline_month)
    except ProductNotFoundError as exc:
        raise _not_found(product_id) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except AnalysisRunUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


# 특정 달의 리뷰 원문 목록(항목·감성으로 거르기, 페이지 단위).
@router.get("/api/v1/products/{product_id}/reviews", response_model=ReviewListResponse)
def reviews(
    product_id: str,
    session: DbSession,
    month: Month,
    aspect: str | None = Query(default=None, max_length=80),
    polarity: str | None = Query(
        default=None, pattern=r"^(positive|negative|neutral|uncertain)$"
    ),
    page: Page = 1,
    page_size: PageSize = 20,
) -> ReviewListResponse:
    try:
        items, total, source_mode = _service(session).list_reviews(
            product_id=product_id,
            month=month,
            aspect=aspect,
            polarity=polarity,
            page=page,
            page_size=page_size,
        )
    except ProductNotFoundError as exc:
        raise _not_found(product_id) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ReviewListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        source_mode=source_mode,
    )
