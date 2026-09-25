from datetime import datetime
from typing import Any

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
