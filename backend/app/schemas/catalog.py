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


# === [리뷰 의미 검색 응답] GET /api/v1/products/{id}/search ===
class ReviewSearchHit(BaseModel):
    similarity: float
    review: ReviewResponse


class ReviewSearchResponse(BaseModel):
    product_id: str
    query: str
    months: list[str]
    embedding_model: str
    # 검색 기간 리뷰 중 임베딩이 준비된 수(모두 준비되지 않았으면 결과가 일부만 대상)
    embedded_reviews: int
    total_reviews: int
    items: list[ReviewSearchHit]


# === [AI 질문 Agent] POST /api/v1/products/{id}/questions ===
class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1500)


class AgentQuestionRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    # 이전 대화(최근 것만). 답변 문맥에만 쓰고 수치·근거로는 쓰지 않습니다.
    history: list[ChatTurn] = Field(default_factory=list, max_length=8)


class AgentToolCall(BaseModel):
    tool: str
    arguments: dict[str, object]
    ok: bool
    duration_ms: int
    summary: str


class AgentCitation(BaseModel):
    review_id: str
    rating: int
    date: str
    excerpt: str


class AgentAnswerResponse(BaseModel):
    product_id: str
    question: str
    search_query: str
    # answered: 인용·수치 검증 통과 / failed: 재생성 후에도 검증 실패(답변 비공개)
    status: Literal["answered", "failed"]
    answer: str | None
    citations: list[AgentCitation]
    tool_calls: list[AgentToolCall]
    generation_attempts: int
    failure_reason: str | None
    notice: str | None
    is_provisional: bool
    model: str
    prompt_version: str
    latency_ms: int
    # 저장된 답을 돌려준 경우(미리 생성한 FAQ 또는 이전에 같은 질문으로 만든 답)
    cached: bool = False
    generated_at: datetime | None = None
    # 답을 만든 시점의 분석 성공 리뷰 수. 지금과 다르면 is_stale=True
    analyzed_count: int | None = None
    is_stale: bool = False


# === [자주 묻는 질문] GET /api/v1/products/{id}/faq ===
class FaqItem(BaseModel):
    key: str
    label: str
    question: str
    answer: AgentAnswerResponse | None


class FaqResponse(BaseModel):
    product_id: str
    analysis_version: str
    current_analyzed_count: int
    items: list[FaqItem]
