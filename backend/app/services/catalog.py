from datetime import datetime

from sqlalchemy.orm import Session

from backend.app.core.analysis_taxonomy import category_labels
from backend.app.core.categories import REAL_CATEGORY_KEYS
from backend.app.core.config import get_settings
from backend.app.models import AnalysisRun, Product, Review
from backend.app.repositories.catalog import (
    AnalysisCoverageAggregate,
    AnalysisRunRepository,
    ProductRepository,
    ReviewRepository,
)
from backend.app.schemas.catalog import (
    ChangeThresholds,
    ComparisonIssue,
    ComparisonResponse,
    CoverageResponse,
    MonthlyReviewStat,
    ProductDetail,
    ProductSummary,
    ReviewLabelResponse,
    ReviewResponse,
)
from backend.app.services.months import month_bounds


class ProductNotFoundError(LookupError):
    pass


class AnalysisRunUnavailableError(RuntimeError):
    pass


class CatalogService:
    def __init__(self, session: Session) -> None:
        self.products = ProductRepository(session)
        self.reviews = ReviewRepository(session)
        self.runs = AnalysisRunRepository(session)

    def categories(self, source_mode: str) -> list[str]:
        stored = self.products.categories(source_mode)
        if source_mode != "real":
            return stored
        # 데이터가 아직 없는 공식 카테고리도 UI에서 '준비 중'으로 선택할 수 있게 노출합니다.
        # 기존 Appliances는 DB에 보존하지만 공식 7개 카테고리 목록에는 섞지 않습니다.
        return list(REAL_CATEGORY_KEYS)

    def list_products(
        self,
        *,
        query: str | None,
        category: str | None,
        source_mode: str,
        page: int,
        page_size: int,
    ) -> tuple[list[ProductSummary], int]:
        products, total = self.products.list(
            query=query,
            category=category,
            source_mode=source_mode,
            page=page,
            page_size=page_size,
        )
        return [self._summary(product) for product in products], total

    def product_detail(self, product_id: str) -> ProductDetail:
        product = self._require_product(product_id)
        summary = self._summary(product)
        return ProductDetail(
            **summary.model_dump(),
            source=product.source,
            parent_asin=product.parent_asin,
            metadata=product.metadata_json,
            monthly_stats=[
                MonthlyReviewStat(
                    month=item.month,
                    review_count=item.review_count,
                    average_rating=item.average_rating,
                )
                for item in self.products.monthly_stats(product.id)
            ],
        )

    def compare(
        self, product_id: str, target_month: str, baseline_month: str
    ) -> ComparisonResponse:
        product = self._require_product(product_id)
        target_start, target_end = month_bounds(target_month)
        baseline_start, baseline_end = month_bounds(baseline_month)
        target_total = self.reviews.count_eligible(product_id, target_start, target_end)
        baseline_total = self.reviews.count_eligible(
            product_id, baseline_start, baseline_end
        )
        target_average_rating = self.reviews.average_rating(
            product_id, target_start, target_end
        )
        baseline_average_rating = self.reviews.average_rating(
            product_id, baseline_start, baseline_end
        )
        run = (
            self.runs.active(product.source_mode)
            if product.source_mode != "real" or product.category in REAL_CATEGORY_KEYS
            else None
        )
        target_analysis = self._analysis_coverage(
            product_id, target_start, target_end, run, target_total
        )
        baseline_analysis = self._analysis_coverage(
            product_id, baseline_start, baseline_end, run, baseline_total
        )
        target_status = self._period_status(target_analysis)
        baseline_status = self._period_status(baseline_analysis)
        coverage = CoverageResponse(
            target_total=target_total,
            target_labeled=target_analysis.labeled,
            baseline_total=baseline_total,
            baseline_labeled=baseline_analysis.labeled,
            target_average_rating=target_average_rating,
            baseline_average_rating=baseline_average_rating,
            target_succeeded=target_analysis.succeeded,
            target_failed=target_analysis.failed,
            target_in_progress=target_analysis.in_progress,
            target_unprocessed=self._unprocessed(target_analysis),
            target_processing_rate=self._processing_rate(target_analysis),
            target_analysis_status=target_status,
            baseline_succeeded=baseline_analysis.succeeded,
            baseline_failed=baseline_analysis.failed,
            baseline_in_progress=baseline_analysis.in_progress,
            baseline_unprocessed=self._unprocessed(baseline_analysis),
            baseline_processing_rate=self._processing_rate(baseline_analysis),
            baseline_analysis_status=baseline_status,
        )

        complete = (
            target_total > 0
            and baseline_total > 0
            and target_status == "complete"
            and baseline_status == "complete"
        )
        any_succeeded = target_analysis.succeeded + baseline_analysis.succeeded > 0
        issues: list[ComparisonIssue] = []
        settings = get_settings()
        taxonomy = category_labels(product.category)
        increase_signal = False
        if run is not None and any_succeeded and target_total > 0 and baseline_total > 0:
            target = {
                (item.aspect, item.detail_label, item.polarity): item
                for item in self.reviews.label_aggregates(
                    product_id, target_start, target_end, run.id
                )
            }
            baseline = {
                (item.aspect, item.detail_label, item.polarity): item
                for item in self.reviews.label_aggregates(
                    product_id, baseline_start, baseline_end, run.id
                )
            }
            for key in target.keys() | baseline.keys():
                target_item = target.get(key)
                baseline_item = baseline.get(key)
                target_count = target_item.count if target_item else 0
                baseline_count = baseline_item.count if baseline_item else 0
                target_rate = (
                    target_count / target_analysis.succeeded
                    if target_analysis.succeeded
                    else None
                )
                baseline_rate = (
                    baseline_count / baseline_analysis.succeeded
                    if baseline_analysis.succeeded
                    else None
                )
                change_pp = (
                    (target_rate - baseline_rate) * 100
                    if target_rate is not None and baseline_rate is not None
                    else None
                )
                meets_threshold = (
                    complete
                    and key[2] == "negative"
                    and target_analysis.succeeded >= settings.analysis_min_review_count
                    and baseline_analysis.succeeded >= settings.analysis_min_review_count
                    and target_count >= settings.analysis_min_negative_count
                    and change_pp is not None
                    and change_pp >= settings.analysis_min_increase_pp
                )
                increase_signal = increase_signal or meets_threshold
                evidence_ids = sorted(
                    set(target_item.review_ids if target_item else ())
                    | set(baseline_item.review_ids if baseline_item else ())
                )
                issues.append(
                    ComparisonIssue(
                        aspect=key[0],
                        aspect_name_ko=taxonomy.get(key[:2], {}).get("aspect_name_ko"),
                        detail_label=key[1],
                        detail_name_ko=taxonomy.get(key[:2], {}).get("detail_name_ko"),
                        polarity=key[2],
                        target_count=target_count,
                        target_total=target_analysis.succeeded,
                        target_rate=target_rate,
                        baseline_count=baseline_count,
                        baseline_total=baseline_analysis.succeeded,
                        baseline_rate=baseline_rate,
                        change_pp=change_pp,
                        meets_increase_threshold=meets_threshold if complete else None,
                        evidence_review_ids=evidence_ids,
                    )
                )
            issues.sort(
                key=lambda item: (
                    -(abs(item.change_pp) if item.change_pp is not None else -1),
                    item.aspect,
                    item.detail_label,
                    item.polarity,
                )
            )

        combined_status = self._combined_status(
            target_status, baseline_status, any_succeeded
        )
        if target_total == 0 or baseline_total == 0:
            signal_status = "insufficient_data"
        elif not complete:
            signal_status = "analysis_incomplete"
        elif increase_signal:
            signal_status = "increase_signal"
        else:
            signal_status = "no_increase_signal"
        thresholds = ChangeThresholds(
            min_review_count=settings.analysis_min_review_count,
            min_negative_count=settings.analysis_min_negative_count,
            min_increase_pp=settings.analysis_min_increase_pp,
        )
        return ComparisonResponse(
            product_id=product_id,
            target_month=target_month,
            baseline_month=baseline_month,
            source_mode=product.source_mode,
            coverage=coverage,
            status=(
                "insufficient_data"
                if target_total == 0 or baseline_total == 0
                else "ok"
                if complete
                else "partial"
                if any_succeeded
                else "insufficient_data"
            ),
            analysis_status=combined_status,
            is_provisional=not complete,
            signal_status=signal_status,
            issues=issues,
            data_version=(
                run.data_version
                if run is not None
                else str(
                    product.metadata_json.get(
                        "review_revision", "amazon-reviews-2023"
                    )
                )
            ),
            analysis_version=run.id if run is not None else "not-analyzed",
            model=run.model if run is not None else None,
            prompt_version=run.prompt_version if run is not None else None,
            label_schema_version=(run.label_schema_version if run is not None else None),
            thresholds=thresholds,
        )

    def list_reviews(
        self,
        *,
        product_id: str,
        month: str,
        aspect: str | None,
        polarity: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ReviewResponse], int, str]:
        product = self._require_product(product_id)
        run = (
            self.runs.active(product.source_mode)
            if product.source_mode != "real" or product.category in REAL_CATEGORY_KEYS
            else None
        )
        start, end = month_bounds(month)
        reviews, total = self.reviews.list(
            product_id=product_id,
            start=start,
            end=end,
            aspect=aspect,
            polarity=polarity,
            run_id=run.id if run is not None else None,
            page=page,
            page_size=page_size,
        )
        return [
            self._review_response(
                review,
                category=product.category,
                active_run_id=run.id if run is not None else None,
            )
            for review in reviews
        ], total, product.source_mode

    def _require_product(self, product_id: str) -> Product:
        product = self.products.get(product_id)
        if product is None:
            raise ProductNotFoundError(product_id)
        return product

    def _summary(self, product: Product) -> ProductSummary:
        return ProductSummary(
            id=product.id,
            title=product.title,
            title_ko=(
                str(product.metadata_json["title_ko"])
                if product.metadata_json.get("title_ko")
                else None
            ),
            category=product.category,
            image_url=product.image_url,
            review_count=self.products.review_count(product.id),
            source_average_rating=(
                float(product.metadata_json["source_average_rating"])
                if product.metadata_json.get("source_average_rating") is not None
                else None
            ),
            source_rating_count=(
                int(product.metadata_json["source_rating_number"])
                if product.metadata_json.get("source_rating_number") is not None
                else None
            ),
            available_months=self.products.available_months(product.id),
            source_mode=product.source_mode,
        )

    @staticmethod
    def _period_status(coverage: AnalysisCoverageAggregate) -> str:
        if coverage.failed > 0:
            return "partial_failure"
        if coverage.total > 0 and coverage.succeeded == coverage.total:
            return "complete"
        if coverage.succeeded > 0 or coverage.in_progress > 0:
            return "in_progress"
        return "not_started"

    @staticmethod
    def _unprocessed(coverage: AnalysisCoverageAggregate) -> int:
        return max(
            coverage.total
            - coverage.succeeded
            - coverage.failed
            - coverage.in_progress,
            0,
        )

    @staticmethod
    def _processing_rate(coverage: AnalysisCoverageAggregate) -> float | None:
        return coverage.succeeded / coverage.total if coverage.total else None

    @staticmethod
    def _combined_status(
        target_status: str, baseline_status: str, any_succeeded: bool
    ) -> str:
        statuses = {target_status, baseline_status}
        if "partial_failure" in statuses:
            return "partial_failure"
        if statuses == {"complete"}:
            return "complete"
        if any_succeeded or "in_progress" in statuses:
            return "in_progress"
        return "not_started"

    def _analysis_coverage(
        self,
        product_id: str,
        start: datetime,
        end: datetime,
        run: AnalysisRun | None,
        total: int,
    ) -> AnalysisCoverageAggregate:
        if run is None:
            return AnalysisCoverageAggregate(total, 0, 0, 0, 0)
        return self.reviews.analysis_coverage(product_id, start, end, run.id)

    @staticmethod
    def _review_response(
        review: Review, *, category: str, active_run_id: str | None
    ) -> ReviewResponse:
        taxonomy = category_labels(category)
        active_result = next(
            (
                result
                for result in review.analysis_results
                if active_run_id is not None and result.run_id == active_run_id
            ),
            None,
        )
        labels = [
            ReviewLabelResponse(
                aspect=label.aspect,
                aspect_name_ko=taxonomy.get(
                    (label.aspect, label.detail_label), {}
                ).get("aspect_name_ko"),
                detail_label=label.detail_label,
                detail_name_ko=taxonomy.get(
                    (label.aspect, label.detail_label), {}
                ).get("detail_name_ko"),
                polarity=label.polarity,
                evidence_span=label.evidence_span,
                analysis_version=label.run_id,
                model=label.run.model,
                prompt_version=label.run.prompt_version,
                label_schema_version=label.run.label_schema_version,
            )
            for label in sorted(
                [
                    item
                    for item in review.labels
                    if active_run_id is not None and item.run_id == active_run_id
                ],
                key=lambda item: (item.aspect, item.detail_label, item.polarity, item.id),
            )
        ]
        return ReviewResponse(
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
            labels=labels,
            analysis_status=(active_result.status if active_result else "not_started"),
            source_mode=review.source_mode,
        )
