"""DB 테이블 설계(SQLAlchemy 모델).

상품 → 리뷰 → AI 분석 결과·라벨 → 임베딩(벡터) → 저장된 챗봇 답의 관계를 정의합니다.
테이블 변경은 Alembic 마이그레이션(backend/migrations)으로 반영합니다.
"""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base


# [상품] 아마존 상품 정보(이름, 카테고리, 사진 주소, 원천 평점, 한국어 이름 등 메타데이터).
class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="fixture")
    parent_asin: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    reviews: Mapped[list["Review"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


# [분석 실행] AI 분류 한 번의 설정 기록(모델·프롬프트·분류 체계 버전). 활성 실행의 결과만 화면에 씁니다.
class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        # fixture와 실제 데이터가 각각 하나의 활성 분석 버전만 사용하게 합니다.
        Index(
            "uq_analysis_runs_active_source",
            "source_mode",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    label_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="fixture")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    target_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    labels: Mapped[list["ReviewLabel"]] = relationship(back_populates="run")
    results: Mapped[list["ReviewAnalysisResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


# [리뷰] 리뷰 원문, 별점, 작성 시각, 번역 캐시.
class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_reviews_rating"),
        Index("ix_reviews_product_reviewed_at", "product_id", "reviewed_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    source_record_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    source_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="fixture")
    asin: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # 영어 원문은 title/text에 그대로 두고, 자동 번역 결과와 생성 정보를 별도 캐시합니다.
    title_ko: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_ko: Mapped[str | None] = mapped_column(Text, nullable=True)
    translation_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    translation_prompt_version: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    translated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    product: Mapped[Product] = relationship(back_populates="reviews")
    labels: Mapped[list["ReviewLabel"]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )
    analysis_results: Mapped[list["ReviewAnalysisResult"]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )
    human_evaluations: Mapped[list["HumanReviewEvaluation"]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )


# [리뷰별 분석 상태] 분석 실행 × 리뷰마다 성공/실패, 시도 횟수, 걸린 시간, 오류 내용.
class ReviewAnalysisResult(Base):
    __tablename__ = "review_analysis_results"
    __table_args__ = (
        UniqueConstraint("run_id", "review_id", name="uq_review_analysis_run_review"),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_review_analysis_status",
        ),
        Index("ix_review_analysis_run_status", "run_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    review_id: Mapped[str] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Ollama가 반환한 load/prompt/output 시간을 원 단위(ns)와 함께 보존합니다.
    model_metrics_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    db_write_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    run: Mapped[AnalysisRun] = relationship(back_populates="results")
    review: Mapped[Review] = relationship(back_populates="analysis_results")


# [사람 평가] 사람이 매긴 정답 라벨(AI 정확도 측정용).
class HumanReviewEvaluation(Base):
    __tablename__ = "human_review_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id", "review_id", name="uq_human_evaluation_dataset_review"
        ),
        UniqueConstraint(
            "dataset_id", "position", name="uq_human_evaluation_dataset_position"
        ),
        CheckConstraint(
            "status IN ('pending', 'completed')",
            name="ck_human_evaluation_status",
        ),
        Index("ix_human_evaluation_dataset_status", "dataset_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(80), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    split: Mapped[str] = mapped_column(String(40), nullable=False)
    review_id: Mapped[str] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False
    )
    prompt_tuning_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    reviewer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    is_normal_empty: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    gold_labels_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    review: Mapped[Review] = relationship(back_populates="human_evaluations")


# [라벨] AI가 붙인 항목 × 감성 라벨과 그 근거 문장(원문 위치 포함). 리뷰 하나에 여러 개 가능.
class ReviewLabel(Base):
    __tablename__ = "review_labels"
    __table_args__ = (
        UniqueConstraint(
            "review_id",
            "aspect",
            "detail_label",
            "polarity",
            "evidence_span",
            "run_id",
            name="uq_review_labels_evidence",
        ),
        Index("ix_review_labels_lookup", "aspect", "polarity", "review_id"),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    review_id: Mapped[str] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False
    )
    aspect: Mapped[str] = mapped_column(String(80), nullable=False)
    detail_label: Mapped[str] = mapped_column(String(120), nullable=False)
    polarity: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_span: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="RESTRICT"), nullable=False
    )

    review: Mapped[Review] = relationship(back_populates="labels")
    run: Mapped[AnalysisRun] = relationship(back_populates="labels")


# === [리뷰 임베딩] 의미 검색(RAG)용 벡터. 리뷰·모델마다 1개, 원문이 바뀌면 content_hash로 감지합니다 ===
EMBEDDING_DIMENSIONS = 1024  # BAAI/bge-m3 dense 벡터 차원


# [임베딩] 리뷰 본문을 bge-m3로 바꾼 1024차원 벡터(pgvector, 의미 검색용).
class ReviewEmbedding(Base):
    __tablename__ = "review_embeddings"
    __table_args__ = (
        UniqueConstraint("review_id", "model", name="uq_review_embeddings_review_model"),
        Index(
            "ix_review_embeddings_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    review_id: Mapped[str] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    model_digest: Mapped[str | None] = mapped_column(String(80), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# === [AI 답변 저장] 미리 생성한 자주 묻는 질문 답변과 한 번 답한 질문의 캐시 ===
# 답변을 만든 시점의 분석 버전·분석 건수를 함께 저장해, 분석이 진행되면 "낡은 답"으로 표시합니다.
class AgentAnswer(Base):
    __tablename__ = "agent_answers"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "question_key", "prompt_version", name="uq_agent_answers_question"
        ),
        CheckConstraint("kind IN ('faq', 'cache')", name="ck_agent_answers_kind"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    faq_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    question_key: Mapped[str] = mapped_column(String(600), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    tool_calls_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    generation_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    is_provisional: Mapped[bool] = mapped_column(Boolean, nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(64), nullable=False)
    analyzed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
