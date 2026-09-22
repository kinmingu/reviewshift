from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.schemas.catalog import (
    CategoryListResponse,
    ComparisonResponse,
    HealthResponse,
    ProductDetail,
    ProductListResponse,
    ReviewListResponse,
)
from backend.app.services.catalog import (
    AnalysisRunUnavailableError,
    CatalogService,
    ProductNotFoundError,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
Month = Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


def _service(session: Session) -> CatalogService:
    return CatalogService(session)


def _not_found(product_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"product not found: {product_id}",
    )


@router.get("/health", response_model=HealthResponse)
def health(session: DbSession) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return HealthResponse(status="degraded", database="unavailable")
    return HealthResponse(status="ok", database="connected")


@router.get("/api/v1/categories", response_model=CategoryListResponse)
def categories(session: DbSession) -> CategoryListResponse:
    settings = get_settings()
    return CategoryListResponse(
        items=_service(session).categories(), source_mode=settings.source_mode
    )


@router.get("/api/v1/products", response_model=ProductListResponse)
def products(
    session: DbSession,
    query: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=120),
    page: Page = 1,
    page_size: PageSize = 20,
) -> ProductListResponse:
    service = _service(session)
    items, total = service.list_products(
        query=query, category=category, page=page, page_size=page_size
    )
    return ProductListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        source_mode=get_settings().source_mode,
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
    polarity: str | None = Query(default=None, pattern=r"^(positive|negative|neutral)$"),
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

