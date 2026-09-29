"""API 응답·요청 형식(Pydantic 스키마).

서버가 화면에 돌려주는 JSON의 모양을 정의하고, 들어오는 값의 길이·범위를 검사합니다.
docs/API_CONTRACT.md와 같은 내용입니다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceMode = Literal["fixture", "real"]


# 서버 상태 확인 응답.
class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["connected", "unavailable"]


# 카테고리 목록 응답.
class CategoryListResponse(BaseModel):
    items: list[str]
    source_mode: SourceMode


# 상품 카드에 쓰는 요약 정보(이름, 사진, 리뷰 수, 분석 수, 좋아요/아쉬워요 비율).
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
    # AI 분석 목표 표본 수(메타데이터 analysis_sample_size). 없으면 저장 리뷰 전체가 대상
    analysis_sample_size: int | None = None
    positive_review_share: float | None = None
    negative_review_share: float | None = None
    # 상세 화면과 같은 완료 판정(최종 실패가 기준 비율 이하이면 complete)
    analysis_status: Literal["not_started", "in_progress", "complete", "partial_failure"] = (
        "not_started"
    )


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
    # AI 분석 표본 수(없으면 저장 리뷰 전체가 대상)와 저장 리뷰 수
    sample_size: int | None = None
    stored_reviews: int = 0


# 항목 하나(예: 배송)의 좋아요/아쉬워요 수와 비율.
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


# 근거로 보여 줄 리뷰 문장 한 건.
class EvidenceExample(BaseModel):
    review_id: str
    rating: int
    reviewed_at: datetime
    evidence_span: str


# 자주 나오는 불만 하나와 근거 예시.
class ComplaintInsight(BaseModel):
    aspect: str
    aspect_name_ko: str | None
    detail_label: str
    detail_name_ko: str | None
    negative_count: int
    negative_rate: float | None
    examples: list[EvidenceExample]


# 월별 리뷰 수·평균 별점·분석 결과.
class MonthlyInsight(BaseModel):
    month: str
    review_count: int
    average_rating: float
    analyzed_count: int
    positive_review_share: float | None
    negative_review_share: float | None


# 최근 두 달 사이 불만 변화 요약.
class LatestChange(BaseModel):
    baseline_month: str
    target_month: str
    signal_status: str
    is_provisional: bool
    top_negative_changes: list["ComparisonIssue"]


# 상품 상세 리포트 전체 응답(별점 분포, 항목별 평가, 불만 TOP, 월별 추이, 최근 변화).
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


# 상품 목록 응답(페이지 정보 포함).
class ProductListResponse(BaseModel):
    items: list[ProductSummary]
    page: int
    page_size: int
    total: int
    source_mode: SourceMode


# 월별 리뷰 수와 평균 별점.
class MonthlyReviewStat(BaseModel):
    month: str
    review_count: int
    average_rating: float


# 상품 상세 정보(요약 + 원천 정보·메타데이터·월별 통계).
class ProductDetail(ProductSummary):
    source: str
    parent_asin: str
    metadata: dict[str, object]
    monthly_stats: list[MonthlyReviewStat]


# 리뷰에 붙은 라벨 하나(항목, 감성, 근거 문장).
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


# 리뷰 한 건(원문, 번역, 별점, 라벨).
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
    # 이 리뷰가 AI 분석 표본에 들어 있는지(표본이 없는 상품은 null)
    in_analysis_sample: bool | None = None


# 리뷰 목록 응답.
class ReviewListResponse(BaseModel):
    items: list[ReviewResponse]
    page: int
    page_size: int
    total: int
    source_mode: SourceMode


# 두 달 비교에서 각 달의 분석 진행 정도.
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


# 두 달 비교에서 항목 하나의 불만 비율 변화.
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


# 변화 신호를 판정하는 기준값(최소 리뷰 수, 최소 증가폭 등).
class ChangeThresholds(BaseModel):
    min_review_count: int
    min_negative_count: int
    min_increase_pp: float
    # 이 비율 이하의 최종 실패는 월 분석 완료로 보고 비율 분모에서 제외합니다.
    max_failure_rate: float


# 두 달 비교 응답 전체.
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
        "insufficient_sample",
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


# [사람 평가] 고를 수 있는 항목 선택지.
class TaxonomyOption(BaseModel):
    aspect_code: str
    aspect_name_ko: str
    detail_code: str
    detail_name_ko: str


# [사람 평가] 사람이 입력한 정답 라벨 하나.
class GoldLabelInput(BaseModel):
    aspect_code: str
    detail_code: str
    polarity: GoldPolarity
    evidence_span: str = Field(min_length=1)


# [사람 평가] 리뷰 한 건에 대한 사람의 평가 내용.
class EvaluationAnnotation(BaseModel):
    reviewer: str | None = None
    status: EvaluationStatus
    is_normal_empty: bool
    gold_labels: list[GoldLabelInput]
    notes: str | None = None
    completed_at: datetime | None = None


# [사람 평가] 평가 저장 요청.
class EvaluationSaveRequest(BaseModel):
    reviewer: str | None = Field(default=None, max_length=120)
    status: EvaluationStatus = "pending"
    is_normal_empty: bool = False
    gold_labels: list[GoldLabelInput] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=5000)


# [사람 평가] 같은 리뷰에 대한 AI 예측(비교용).
class EvaluationPrediction(BaseModel):
    status: Literal["not_run", "pending", "running", "succeeded", "failed"]
    analysis_version: str | None = None
    labels: list[ReviewLabelResponse] = Field(default_factory=list)
    error: str | None = None


# [사람 평가] 평가 화면 한 장에 필요한 모든 정보.
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


# [사람 평가] 진행 현황.
class EvaluationProgressResponse(BaseModel):
    dataset_id: str
    total: int
    completed: int
    pending: int
    next_pending_position: int | None
    independent_evaluation: bool


# 리뷰 번역 결과.
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


# 리뷰 의미 검색 결과(비슷한 순서).
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


# 챗봇 질문 요청(질문과 최근 대화).
class AgentQuestionRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    # 이전 대화(최근 것만). 답변 문맥에만 쓰고 수치·근거로는 쓰지 않습니다.
    history: list[ChatTurn] = Field(default_factory=list, max_length=8)


# 챗봇이 호출한 도구 기록(무슨 도구를, 성공 여부, 걸린 시간).
class AgentToolCall(BaseModel):
    tool: str
    arguments: dict[str, object]
    ok: bool
    duration_ms: int
    summary: str
    # mcp_stdio / mcp_memory: MCP 프로토콜로 호출, direct: 함수 직접 호출(테스트)
    transport: str = "direct"


# 챗봇 답변이 인용한 리뷰.
class AgentCitation(BaseModel):
    review_id: str
    rating: int
    date: str
    excerpt: str


# 챗봇 AI 답변 응답(답, 인용 리뷰, 도구 기록, 검증 결과, 버전).
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


# 자주 묻는 질문과 미리 만들어 둔 답 목록.
class FaqResponse(BaseModel):
    product_id: str
    analysis_version: str
    current_analyzed_count: int
    items: list[FaqItem]


# === [이상징후 탐지] GET /api/v1/anomalies ===
class AnomalyItem(BaseModel):
    level: Literal["anomaly", "watch"]
    product_id: str
    product_name_ko: str | None
    category: str
    image_url: str | None
    baseline_month: str
    target_month: str
    aspect: str
    detail_label: str
    detail_name_ko: str | None
    baseline_count: int
    baseline_total: int
    target_count: int
    target_total: int
    baseline_rate: float | None
    target_rate: float | None
    change_pp: float | None
    # 한쪽 Fisher 정확 검정 p값과 Benjamini-Hochberg 보정 q값
    p_value: float
    q_value: float
    is_provisional: bool
    evidence_review_ids: list[str]


# 이상징후(불만 급증) 검정 결과 전체.
class AnomalyReport(BaseModel):
    method_version: str
    method: str
    products_total: int
    products_evaluable: int
    pairs_evaluated: int
    pairs_insufficient: int
    tests: int
    items: list[AnomalyItem]
