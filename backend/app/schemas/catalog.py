from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceMode = Literal["fixture", "real"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["connected", "unavailable"]


class CategoryListResponse(BaseModel):
    items: list[str]
    source_mode: SourceMode


class ProductSummary(BaseModel):
    id: str
    title: str
    category: str
    image_url: str | None
    review_count: int
    available_months: list[str]
    source_mode: SourceMode


class ProductListResponse(BaseModel):
    items: list[ProductSummary]
    page: int
    page_size: int
    total: int
    source_mode: SourceMode


class MonthlyReviewStat(BaseModel):
    month: str
    review_count: int
    average_rating: float


class ProductDetail(ProductSummary):
    source: str
    parent_asin: str
    metadata: dict[str, object]
    monthly_stats: list[MonthlyReviewStat]


class ReviewLabelResponse(BaseModel):
    aspect: str
    detail_label: str
    polarity: str
    evidence_span: str
    analysis_version: str


class ReviewResponse(BaseModel):
    id: str
    title: str | None
    text: str
    rating: int
    reviewed_at: datetime
    labels: list[ReviewLabelResponse]
    source_mode: SourceMode


class ReviewListResponse(BaseModel):
    items: list[ReviewResponse]
    page: int
    page_size: int
    total: int
    source_mode: SourceMode


class CoverageResponse(BaseModel):
    target_total: int
    target_labeled: int
    baseline_total: int
    baseline_labeled: int
    target_average_rating: float | None
    baseline_average_rating: float | None


class ComparisonIssue(BaseModel):
    aspect: str
    detail_label: str
    polarity: str
    target_count: int
    target_total: int
    target_rate: float = Field(ge=0, le=1)
    baseline_count: int
    baseline_total: int
    baseline_rate: float = Field(ge=0, le=1)
    change_pp: float
    evidence_review_ids: list[str]


class ComparisonResponse(BaseModel):
    product_id: str
    target_month: str
    baseline_month: str
    source_mode: SourceMode
    coverage: CoverageResponse
    status: Literal["ok", "insufficient_data"]
    issues: list[ComparisonIssue]
    data_version: str
    analysis_version: str

    model_config = ConfigDict(from_attributes=True)
