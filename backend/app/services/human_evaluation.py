from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.app.core.analysis_taxonomy import category_labels
from backend.app.core.config import get_settings
from backend.app.models import (
    HumanReviewEvaluation,
    Review,
    ReviewAnalysisResult,
    ReviewLabel,
)
from backend.app.schemas.catalog import (
    EvaluationAnnotation,
    EvaluationItemResponse,
    EvaluationPrediction,
    EvaluationProgressResponse,
    EvaluationSaveRequest,
    GoldLabelInput,
    ReviewLabelResponse,
    ReviewResponse,
    TaxonomyOption,
    TranslationResponse,
)
from backend.app.services.review_classification import ClassificationError, parse_classification
from backend.app.services.review_translation import (
    PROMPT_VERSION as TRANSLATION_PROMPT_VERSION,
)
from backend.app.services.review_translation import OllamaReviewTranslator

DEFAULT_DATASET_ID = "human-eval-140-v1"


class EvaluationNotFoundError(LookupError):
    pass


class EvaluationValidationError(ValueError):
    pass


class HumanEvaluationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def progress(self, dataset_id: str) -> EvaluationProgressResponse:
        rows = self.session.execute(
            select(HumanReviewEvaluation.status, func.count())
            .where(HumanReviewEvaluation.dataset_id == dataset_id)
            .group_by(HumanReviewEvaluation.status)
        ).all()
        counts = dict(rows)
        total = int(sum(counts.values()))
        if total == 0:
            raise EvaluationNotFoundError(dataset_id)
        next_position = self.session.scalar(
            select(HumanReviewEvaluation.position)
            .where(
                HumanReviewEvaluation.dataset_id == dataset_id,
                HumanReviewEvaluation.status == "pending",
            )
            .order_by(HumanReviewEvaluation.position)
            .limit(1)
        )
        non_independent = int(
            self.session.scalar(
                select(func.count())
                .select_from(HumanReviewEvaluation)
                .where(
                    HumanReviewEvaluation.dataset_id == dataset_id,
                    (HumanReviewEvaluation.split != "independent_evaluation")
                    | HumanReviewEvaluation.prompt_tuning_used.is_(True),
                )
            )
            or 0
        )
        return EvaluationProgressResponse(
            dataset_id=dataset_id,
            total=total,
            completed=int(counts.get("completed", 0)),
            pending=int(counts.get("pending", 0)),
            next_pending_position=int(next_position) if next_position is not None else None,
            independent_evaluation=non_independent == 0,
        )

    def item(self, dataset_id: str, position: int) -> EvaluationItemResponse:
        item = self.session.scalar(
            select(HumanReviewEvaluation)
            .options(
                selectinload(HumanReviewEvaluation.review).selectinload(Review.product),
                selectinload(HumanReviewEvaluation.review)
                .selectinload(Review.analysis_results)
                .selectinload(ReviewAnalysisResult.run),
                selectinload(HumanReviewEvaluation.review)
                .selectinload(Review.labels)
                .selectinload(ReviewLabel.run),
            )
            .where(
                HumanReviewEvaluation.dataset_id == dataset_id,
                HumanReviewEvaluation.position == position,
            )
        )
        if item is None:
            raise EvaluationNotFoundError(f"{dataset_id}:{position}")
        total = int(
            self.session.scalar(
                select(func.count())
                .select_from(HumanReviewEvaluation)
                .where(HumanReviewEvaluation.dataset_id == dataset_id)
            )
            or 0
        )
        review = item.review
        product = review.product
        options = [
            TaxonomyOption(
                aspect_code=aspect,
                aspect_name_ko=value["aspect_name_ko"],
                detail_code=detail,
                detail_name_ko=value["detail_name_ko"],
            )
            for (aspect, detail), value in category_labels(product.category).items()
        ]
        prediction = self._prediction(review, product.category) if item.status == "completed" else None
        return EvaluationItemResponse(
            dataset_id=dataset_id,
            position=item.position,
            total=total,
            split=item.split,
            prompt_tuning_used=item.prompt_tuning_used,
            product_id=product.id,
            product_name=product.title,
            product_name_ko=product.metadata_json.get("title_ko"),
            category=product.category,
            review=ReviewResponse(
                id=review.id,
                title=review.title,
                text=review.text,
                title_ko=review.title_ko,
                text_ko=review.text_ko,
                translation_model=review.translation_model,
                translation_prompt_version=review.translation_prompt_version,
                translated_at=review.translated_at,
                rating=review.rating,
                reviewed_at=review.reviewed_at,
                labels=[],
                analysis_status="not_started",
                source_mode=review.source_mode,
            ),
            taxonomy=options,
            annotation=EvaluationAnnotation(
                reviewer=item.reviewer,
                status=item.status,
                is_normal_empty=item.is_normal_empty,
                gold_labels=[GoldLabelInput(**value) for value in item.gold_labels_json],
                notes=item.notes,
                completed_at=item.completed_at,
            ),
            prediction_revealed=item.status == "completed",
            prediction=prediction,
        )

    def save(
        self, dataset_id: str, position: int, payload: EvaluationSaveRequest
    ) -> EvaluationItemResponse:
        item = self.session.scalar(
            select(HumanReviewEvaluation)
            .options(selectinload(HumanReviewEvaluation.review).selectinload(Review.product))
            .where(
                HumanReviewEvaluation.dataset_id == dataset_id,
                HumanReviewEvaluation.position == position,
            )
        )
        if item is None:
            raise EvaluationNotFoundError(f"{dataset_id}:{position}")
        if payload.is_normal_empty and payload.gold_labels:
            raise EvaluationValidationError("정상 빈 라벨과 항목 라벨을 동시에 저장할 수 없습니다.")
        if payload.status == "completed":
            if not (payload.reviewer or "").strip():
                raise EvaluationValidationError("검토 완료에는 검토자 이름이 필요합니다.")
            if not payload.is_normal_empty and not payload.gold_labels:
                raise EvaluationValidationError(
                    "라벨이 없다면 '정상 빈 라벨'을 선택하거나 진행 중으로 저장해 주세요."
                )

        review = item.review
        raw_labels = [label.model_dump() for label in payload.gold_labels]
        # 모델 출력과 같은 taxonomy·원문 구간·단어 경계 검사를 사람 정답에도 적용합니다.
        # 다만 사람은 한 단어 근거도 의도적으로 고를 수 있으므로 최소 단어 수는 1로 둡니다.
        try:
            parse_classification(
                json.dumps({"labels": raw_labels}, ensure_ascii=False),
                category=review.product.category,
                title=review.title,
                text=review.text,
                min_evidence_words=1,
            )
        except ClassificationError as exc:
            raise EvaluationValidationError(str(exc)) from exc
        item.reviewer = (payload.reviewer or "").strip() or None
        item.status = payload.status
        item.is_normal_empty = payload.is_normal_empty
        item.gold_labels_json = raw_labels
        item.notes = (payload.notes or "").strip() or None
        item.completed_at = datetime.now(UTC) if payload.status == "completed" else None
        self.session.commit()
        return self.item(dataset_id, position)

    def translate(self, review_id: str) -> TranslationResponse:
        review = self.session.get(Review, review_id)
        if review is None:
            raise EvaluationNotFoundError(review_id)
        if not review.text_ko:
            settings = get_settings()
            translator = OllamaReviewTranslator(
                model=settings.ollama_model,
                base_url=settings.ollama_base_url,
            )
            translated = translator.translate(review.title, review.text)
            review.title_ko = translated.title_ko
            review.text_ko = translated.text_ko
            review.translation_model = settings.ollama_model
            review.translation_prompt_version = TRANSLATION_PROMPT_VERSION
            review.translated_at = datetime.now(UTC)
            self.session.commit()
        return TranslationResponse(
            review_id=review.id,
            title_ko=review.title_ko or "",
            text_ko=review.text_ko or "",
            translation_model=review.translation_model or "",
            translation_prompt_version=review.translation_prompt_version or "",
            translated_at=review.translated_at or datetime.now(UTC),
        )

    def export_csv(self, dataset_id: str) -> str:
        items = list(
            self.session.scalars(
                select(HumanReviewEvaluation)
                .options(
                    selectinload(HumanReviewEvaluation.review).selectinload(Review.product)
                )
                .where(HumanReviewEvaluation.dataset_id == dataset_id)
                .order_by(HumanReviewEvaluation.position)
            )
        )
        if not items:
            raise EvaluationNotFoundError(dataset_id)
        output = io.StringIO()
        fields = [
            "sample_id",
            "product_id",
            "parent_asin",
            "product_name_ko",
            "category",
            "review_id",
            "month",
            "rating",
            "title_en",
            "text_en",
            "title_ko_reference",
            "text_ko_reference",
            "translation_notice",
            "gold_labels_json",
            "ambiguity_or_error_notes",
            "reviewer",
            "review_status",
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for item in items:
            review = item.review
            product = review.product
            writer.writerow(
                {
                    "sample_id": f"evaluation-{item.position:03d}",
                    "product_id": product.id,
                    "parent_asin": product.parent_asin,
                    "product_name_ko": product.metadata_json.get("title_ko") or "",
                    "category": product.category,
                    "review_id": review.id,
                    "month": review.reviewed_at.strftime("%Y-%m"),
                    "rating": review.rating,
                    "title_en": review.title or "",
                    "text_en": review.text,
                    "title_ko_reference": review.title_ko or "",
                    "text_ko_reference": review.text_ko or "",
                    "translation_notice": "자동 번역 참고용" if review.text_ko else "번역 없음",
                    "gold_labels_json": json.dumps(
                        item.gold_labels_json, ensure_ascii=False
                    ),
                    "ambiguity_or_error_notes": item.notes or "",
                    "reviewer": item.reviewer or "",
                    "review_status": item.status,
                }
            )
        return output.getvalue()

    def _prediction(self, review: Review, category: str) -> EvaluationPrediction:
        results = sorted(
            review.analysis_results,
            key=lambda value: value.updated_at,
            reverse=True,
        )
        if not results:
            return EvaluationPrediction(status="not_run")
        result = results[0]
        taxonomy = category_labels(category)
        labels = [
            ReviewLabelResponse(
                aspect=label.aspect,
                aspect_name_ko=taxonomy.get((label.aspect, label.detail_label), {}).get(
                    "aspect_name_ko"
                ),
                detail_label=label.detail_label,
                detail_name_ko=taxonomy.get((label.aspect, label.detail_label), {}).get(
                    "detail_name_ko"
                ),
                polarity=label.polarity,
                evidence_span=label.evidence_span,
                analysis_version=label.run_id,
                model=result.run.model,
                prompt_version=result.run.prompt_version,
                label_schema_version=result.run.label_schema_version,
            )
            for label in review.labels
            if label.run_id == result.run_id
        ]
        return EvaluationPrediction(
            status=result.status,
            analysis_version=result.run_id,
            labels=labels,
            error=result.last_error,
        )
