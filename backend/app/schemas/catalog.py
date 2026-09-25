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
    title_ko: str | None
    category: str
    image_url: str | None
    review_count: int
    source_average_rating: float | None
    source_rating_count: int | None
    available_months: list[str]
    source_mode: SourceMode
    # 상품 카드용 활성 분석 요약. 분석된 리뷰가 없으면 비율은 null입니다.
    analyzed_review_count: int = 0
    positive_review_share: float | None = None
    negative_review_share: float | None = None


# === [상품 리뷰 리포트 응답] GET /api/v1/products/{id}/insights ===
class AnalysisOverview(BaseModel):
    total: int
    succeeded: int
    failed: int
    in_progress: int
    unprocessed: int
    processing_rate: float | None
    status: Literal["not_started", "in_progress", "complete", "partial_failure"]
    analysis_version: str
    model: str | None
    prompt_version: str | None
    label_schema_version: str | None


class AspectInsight(BaseModel):
    aspect: str
    aspect_name_ko: str | None
    detail_label: str
    detail_name_ko: str | None
    mention_count: int
    positive_count: int
    negative_count: int
    neutral_count: int
    uncertain_count: int
    # 분모는 분류에 성공한 리뷰 수입니다. 성공 리뷰가 없으면 null입니다.
    mention_rate: float | None
    positive_rate: float | None
    negative_rate: float | None


class EvidenceExample(BaseModel):
    review_id: str
    rating: int
    reviewed_at: datetime
    evidence_span: str


class ComplaintInsight(BaseModel):
    aspect: str
    aspect_name_ko: str | None
    detail_label: str
    detail_name_ko: str | None
    negative_count: int
    negative_rate: float | None
    examples: list[EvidenceExample]


class MonthlyInsight(BaseModel):
    month: str
    review_count: int
    average_rating: float
    analyzed_count: int
    positive_review_share: float | None
    negative_review_share: float | None


class LatestChange(BaseModel):
    baseline_month: str
    target_month: str
    signal_status: str
    is_provisional: bool
    top_negative_changes: list["ComparisonIssue"]


class ProductInsightResponse(BaseModel):
    product_id: str
    source_mode: SourceMode
    review_count: int
    average_rating: float | None
    rating_distribution: dict[int, int]
    analysis: AnalysisOverview
    positive_review_share: float | None
    negative_review_share: float | None
    aspects: list[AspectInsight]
    top_complaints: list[ComplaintInsight]
    monthly: list[MonthlyInsight]
    latest_change: LatestChange | None
    data_version: str


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
    aspect_name_ko: str | None = None
    detail_label: str
    detail_name_ko: str | None = None
    polarity: str
    evidence_span: str
    analysis_version: str
    model: str | None = None
    prompt_version: str | None = None
    label_schema_version: str | None = None


class ReviewResponse(BaseModel):
    id: str
    title: str | None
    text: str
    title_ko: str | None = None
    text_ko: str | None = None
    translation_model: str | None = None
    translation_prompt_version: str | None = None
    translated_at: datetime | None = None
    rating: int
    reviewed_at: datetime
    labels: list[ReviewLabelResponse]
    analysis_status: Literal[
        "not_started", "pending", "running", "succeeded", "failed"
    ]
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
    target_succeeded: int
    target_failed: int
    target_in_progress: int
    target_unprocessed: int
    target_processing_rate: float | None
    target_analysis_status: Literal[
        "not_started", "in_progress", "complete", "partial_failure"
    ]
    baseline_succeeded: int
    baseline_failed: int
    baseline_in_progress: int
    baseline_unprocessed: int
    baseline_processing_rate: float | None
    baseline_analysis_status: Literal[
        "not_started", "in_progress", "complete", "partial_failure"
    ]


class ComparisonIssue(BaseModel):
    aspect: str
    aspect_name_ko: str | None = None
    detail_label: str
    detail_name_ko: str | None = None
    polarity: str
    target_count: int
    target_total: int
    target_rate: float | None = Field(default=None, ge=0, le=1)
    baseline_count: int
    baseline_total: int
    baseline_rate: float | None = Field(default=None, ge=0, le=1)
    change_pp: float | None
    meets_increase_threshold: bool | None
    evidence_review_ids: list[str]


class ChangeThresholds(BaseModel):
    min_review_count: int
    min_negative_count: int
    min_increase_pp: float
    # 이 비율 이하의 최종 실패는 월 분석 완료로 보고 비율 분모에서 제외합니다.
    max_failure_rate: float


class ComparisonResponse(BaseModel):
    product_id: str
    target_month: str
    baseline_month: str
    source_mode: SourceMode
    coverage: CoverageResponse
    status: Literal["ok", "partial", "insufficient_data"]
    analysis_status: Literal[
        "not_started", "in_progress", "complete", "partial_failure"
    ]
    is_provisional: bool
    signal_status: Literal[
        "analysis_incomplete",
        "insufficient_data",
        "no_increase_signal",
        "increase_signal",
    ]
    issues: list[ComparisonIssue]
    data_version: str
    analysis_version: str
    model: str | None
    prompt_version: str | None
    label_schema_version: str | None
    thresholds: ChangeThresholds

    model_config = ConfigDict(from_attributes=True)


EvaluationStatus = Literal["pending", "completed"]
GoldPolarity = Literal["positive", "negative", "neutral", "uncertain"]


class TaxonomyOption(BaseModel):
    aspect_code: str
    aspect_name_ko: str
    detail_code: str
    detail_name_ko: str


class GoldLabelInput(BaseModel):
    aspect_code: str
    detail_code: str
    polarity: GoldPolarity
    evidence_span: str = Field(min_length=1)


class EvaluationAnnotation(BaseModel):
    reviewer: str | None = None
    status: EvaluationStatus
    is_normal_empty: bool
    gold_labels: list[GoldLabelInput]
    notes: str | None = None
    completed_at: datetime | None = None


class EvaluationSaveRequest(BaseModel):
    reviewer: str | None = Field(default=None, max_length=120)
    status: EvaluationStatus = "pending"
    is_normal_empty: bool = False
    gold_labels: list[GoldLabelInput] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=5000)


class EvaluationPrediction(BaseModel):
    status: Literal["not_run", "pending", "running", "succeeded", "failed"]
    analysis_version: str | None = None
    labels: list[ReviewLabelResponse] = Field(default_factory=list)
    error: str | None = None


class EvaluationItemResponse(BaseModel):
    dataset_id: str
    position: int
    total: int
    split: str
    prompt_tuning_used: bool
    product_id: str
    product_name: str
    product_name_ko: str | None
    category: str
    review: ReviewResponse
    taxonomy: list[TaxonomyOption]
    annotation: EvaluationAnnotation
    prediction_revealed: bool
    prediction: EvaluationPrediction | None = None


class EvaluationProgressResponse(BaseModel):
    dataset_id: str
    total: int
    completed: int
    pending: int
    next_pending_position: int | None
    independent_evaluation: bool


class TranslationResponse(BaseModel):
    review_id: str
    title_ko: str
    text_ko: str
    translation_model: str
    translation_prompt_version: str
    translated_at: datetime


# LatestChange는 파일 뒤쪽에 정의된 ComparisonIssue를 참조하므로 마지막에 확정합니다.
LatestChange.model_rebuild()
