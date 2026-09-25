from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.schemas.catalog import (
    CategoryListResponse,
    ComparisonResponse,
    EvaluationItemResponse,
    EvaluationProgressResponse,
    EvaluationSaveRequest,
    HealthResponse,
    ProductDetail,
    ProductListResponse,
    ReviewListResponse,
    TranslationResponse,
)
from backend.app.services.catalog import (
    AnalysisRunUnavailableError,
    CatalogService,
    ProductNotFoundError,
)
from backend.app.services.human_evaluation import (
    EvaluationNotFoundError,
    EvaluationValidationError,
    HumanEvaluationService,
)
from backend.app.services.review_translation import TranslationError

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
Month = Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
SourceModeParam = Annotated[str, Query(pattern=r"^(fixture|real)$")]


def _service(session: Session) -> CatalogService:
    return CatalogService(session)


def _not_found(product_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"product not found: {product_id}",
    )


def _evaluation_service(session: Session) -> HumanEvaluationService:
    return HumanEvaluationService(session)


@router.get(
    "/api/v1/evaluation/datasets/{dataset_id}/progress",
    response_model=EvaluationProgressResponse,
)
def evaluation_progress(dataset_id: str, session: DbSession) -> EvaluationProgressResponse:
    try:
        return _evaluation_service(session).progress(dataset_id)
    except EvaluationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="평가 데이터셋을 찾을 수 없습니다.") from exc


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


@router.post("/api/v1/reviews/{review_id}/translate", response_model=TranslationResponse)
def translate_review(review_id: str, session: DbSession) -> TranslationResponse:
    try:
        return _evaluation_service(session).translate(review_id)
    except EvaluationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="리뷰를 찾을 수 없습니다.") from exc
    except TranslationError as exc:
        raise HTTPException(status_code=503, detail=f"번역 모델 처리 실패: {exc}") from exc


@router.get("/health", response_model=HealthResponse)
def health(session: DbSession) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return HealthResponse(status="degraded", database="unavailable")
    return HealthResponse(status="ok", database="connected")


@router.get("/api/v1/categories", response_model=CategoryListResponse)
def categories(
    session: DbSession, source_mode: SourceModeParam | None = None
) -> CategoryListResponse:
    selected_mode = source_mode or get_settings().source_mode
    return CategoryListResponse(
        items=_service(session).categories(selected_mode), source_mode=selected_mode
    )


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


@router.get("/api/v1/products/{product_id}", response_model=ProductDetail)
def product_detail(product_id: str, session: DbSession) -> ProductDetail:
    try:
        return _service(session).product_detail(product_id)
    except ProductNotFoundError as exc:
        raise _not_found(product_id) from exc


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
