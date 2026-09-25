from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.core.analysis_taxonomy import category_labels
from backend.app.core.categories import REAL_CATEGORY_KEYS
from backend.app.core.config import get_settings
from backend.app.models import AnalysisRun, Product, Review
from backend.app.repositories.catalog import (
    AnalysisCoverageAggregate,
    AnalysisRunRepository,
    ProductInsightRepository,
    ProductRepository,
    ReviewRepository,
)
from backend.app.schemas.catalog import (
    AnalysisOverview,
    AspectInsight,
    ChangeThresholds,
    ComparisonIssue,
    ComparisonResponse,
    ComplaintInsight,
    CoverageResponse,
    EvidenceExample,
    LatestChange,
    MonthlyInsight,
    MonthlyReviewStat,
    ProductDetail,
    ProductInsightResponse,
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
        self.insights = ProductInsightRepository(session)

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
        # 변화율은 "이전 달 → 이후 달" 방향만 의미가 있으므로 같은 달·역방향 비교를 막습니다.
        if baseline_start >= target_start:
            raise ValueError("baseline_month must be earlier than target_month")
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
        run = self._active_run(product)
        target_analysis = self._analysis_coverage(
            product_id, target_start, target_end, run, target_total
        )
        baseline_analysis = self._analysis_coverage(
            product_id, baseline_start, baseline_end, run, baseline_total
        )
        settings = get_settings()
        target_status = self._period_status(
            target_analysis, settings.analysis_max_failure_rate
        )
        baseline_status = self._period_status(
            baseline_analysis, settings.analysis_max_failure_rate
        )
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
            max_failure_rate=settings.analysis_max_failure_rate,
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
        run = self._active_run(product)
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

    # === [상품 리뷰 리포트] 상세 화면의 별점 분포·항목별 평가·주요 불만·월별 추이·최근 변화 ===
    def product_insights(self, product_id: str) -> ProductInsightResponse:
        """상품 전체 저장 기간의 리뷰 리포트를 SQL 집계로 만듭니다(LLM이 수치를 만들지 않음).

        비율의 분모는 활성 분석 run에서 분류에 성공한 리뷰 수입니다. 분석 전·실패 리뷰는
        불만 없는 리뷰로 세지 않습니다.
        """
        product = self._require_product(product_id)
        run = self._active_run(product)
        settings = get_settings()
        taxonomy = category_labels(product.category)
        distribution = self.insights.rating_distribution(product_id)
        review_count = sum(distribution.values())
        average_rating = (
            sum(rating * count for rating, count in distribution.items()) / review_count
            if review_count
            else None
        )

        # 상품 전체 기간의 처리 현황(월 비교와 같은 완료 판정 규칙)
        all_time = self._analysis_coverage(
            product_id,
            datetime(1990, 1, 1, tzinfo=UTC),
            datetime(2101, 1, 1, tzinfo=UTC),
            run,
            review_count,
        )
        succeeded = all_time.succeeded
        analysis = AnalysisOverview(
            total=all_time.total,
            succeeded=succeeded,
            failed=all_time.failed,
            in_progress=all_time.in_progress,
            unprocessed=self._unprocessed(all_time),
            processing_rate=self._processing_rate(all_time),
            status=self._period_status(all_time, settings.analysis_max_failure_rate),
            analysis_version=run.id if run is not None else "not-analyzed",
            model=run.model if run is not None else None,
            prompt_version=run.prompt_version if run is not None else None,
            label_schema_version=run.label_schema_version if run is not None else None,
        )

        def rate(count: int) -> float | None:
            return count / succeeded if succeeded else None

        aspects: list[AspectInsight] = []
        complaints: list[ComplaintInsight] = []
        positive_share = negative_share = None
        monthly_analysis = {}
        if run is not None and succeeded:
            polarity_reviews = self.insights.polarity_review_counts(product_id, run.id)
            positive_share = rate(polarity_reviews.get("positive", 0))
            negative_share = rate(polarity_reviews.get("negative", 0))

            counts: dict[tuple[str, str], dict[str, int]] = {}
            for aspect, detail, polarity, count in self.insights.label_counts(
                product_id, run.id
            ):
                counts.setdefault((aspect, detail), {})[polarity] = count
            mentions = self.insights.mention_counts(product_id, run.id)
            for (aspect, detail), by_polarity in counts.items():
                names = taxonomy.get((aspect, detail), {})
                aspects.append(
                    AspectInsight(
                        aspect=aspect,
                        aspect_name_ko=names.get("aspect_name_ko"),
                        detail_label=detail,
                        detail_name_ko=names.get("detail_name_ko"),
                        mention_count=mentions.get((aspect, detail), 0),
                        positive_count=by_polarity.get("positive", 0),
                        negative_count=by_polarity.get("negative", 0),
                        neutral_count=by_polarity.get("neutral", 0),
                        uncertain_count=by_polarity.get("uncertain", 0),
                        mention_rate=rate(mentions.get((aspect, detail), 0)),
                        positive_rate=rate(by_polarity.get("positive", 0)),
                        negative_rate=rate(by_polarity.get("negative", 0)),
                    )
                )
            aspects.sort(key=lambda item: (-item.mention_count, item.aspect, item.detail_label))

            negatives = sorted(
                (item for item in aspects if item.negative_count > 0),
                key=lambda item: (-item.negative_count, item.aspect, item.detail_label),
            )[:3]
            for item in negatives:
                complaints.append(
                    ComplaintInsight(
                        aspect=item.aspect,
                        aspect_name_ko=item.aspect_name_ko,
                        detail_label=item.detail_label,
                        detail_name_ko=item.detail_name_ko,
                        negative_count=item.negative_count,
                        negative_rate=item.negative_rate,
                        examples=[
                            EvidenceExample(
                                review_id=example.review_id,
                                rating=example.rating,
                                reviewed_at=example.reviewed_at,
                                evidence_span=example.evidence_span,
                            )
                            for example in self.insights.label_examples(
                                product_id,
                                run.id,
                                item.aspect,
                                item.detail_label,
                                "negative",
                                limit=3,
                            )
                        ],
                    )
                )
            monthly_analysis = {
                item.month: item for item in self.insights.monthly_analysis(product_id, run.id)
            }

        monthly = []
        for stat in self.products.monthly_stats(product_id):
            analyzed = monthly_analysis.get(stat.month)
            analyzed_count = analyzed.succeeded if analyzed else 0
            monthly.append(
                MonthlyInsight(
                    month=stat.month,
                    review_count=stat.review_count,
                    average_rating=stat.average_rating,
                    analyzed_count=analyzed_count,
                    positive_review_share=(
                        analyzed.positive_reviews / analyzed_count if analyzed_count else None
                    ),
                    negative_review_share=(
                        analyzed.negative_reviews / analyzed_count if analyzed_count else None
                    ),
                )
            )

        # 최근 변화: 기간을 결과로 고르지 않고 항상 "인접한 마지막 두 달"을 같은 규칙으로 비교합니다.
        latest_change = None
        months = [item.month for item in monthly]
        if len(months) >= 2:
            comparison = self.compare(product_id, months[-1], months[-2])
            increases = sorted(
                (
                    issue
                    for issue in comparison.issues
                    if issue.polarity == "negative"
                    and issue.change_pp is not None
                    and issue.change_pp > 0
                ),
                key=lambda issue: (-(issue.change_pp or 0), issue.aspect, issue.detail_label),
            )[:3]
            latest_change = LatestChange(
                baseline_month=months[-2],
                target_month=months[-1],
                signal_status=comparison.signal_status,
                is_provisional=comparison.is_provisional,
                top_negative_changes=increases,
            )

        return ProductInsightResponse(
            product_id=product_id,
            source_mode=product.source_mode,
            review_count=review_count,
            average_rating=average_rating,
            rating_distribution=distribution,
            analysis=analysis,
            positive_review_share=positive_share,
            negative_review_share=negative_share,
            aspects=aspects,
            top_complaints=complaints,
            monthly=monthly,
            latest_change=latest_change,
            data_version=(
                run.data_version
                if run is not None
                else str(product.metadata_json.get("review_revision", "amazon-reviews-2023"))
            ),
        )

    def _active_run(self, product: Product) -> AnalysisRun | None:
        # 기존 Appliances 실제 상품은 공식 7개 카테고리 분석 run의 대상이 아닙니다.
        if product.source_mode == "real" and product.category not in REAL_CATEGORY_KEYS:
            return None
        return self.runs.active(product.source_mode)

    def _require_product(self, product_id: str) -> Product:
        product = self.products.get(product_id)
        if product is None:
            raise ProductNotFoundError(product_id)
        return product

    def _card_analysis(self, product: Product) -> tuple[int, float | None, float | None]:
        run = self._active_run(product)
        if run is None:
            return 0, None, None
        analyzed = self.insights.succeeded_count(product.id, run.id)
        if not analyzed:
            return 0, None, None
        polarity_reviews = self.insights.polarity_review_counts(product.id, run.id)
        return (
            analyzed,
            polarity_reviews.get("positive", 0) / analyzed,
            polarity_reviews.get("negative", 0) / analyzed,
        )

    def _summary(self, product: Product) -> ProductSummary:
        analyzed, positive_share, negative_share = self._card_analysis(product)
        return ProductSummary(
            analyzed_review_count=analyzed,
            positive_review_share=positive_share,
            negative_review_share=negative_share,
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

    # === [기간 분석 상태] 처리 완료 여부와 실패 허용 기준으로 비교 가능 여부를 정합니다 ===
    @staticmethod
    def _period_status(coverage: AnalysisCoverageAggregate, max_failure_rate: float) -> str:
        """재시도해도 계속 실패하는 리뷰 1건 때문에 기간 전체가 영원히 미완료가 되지 않게 합니다.

        - 모든 리뷰가 성공 또는 최종 실패로 끝났고 실패율이 기준 이하 → complete
          (실패 리뷰는 비율 분모에서 빠지고, 실패 건수는 coverage에 그대로 남습니다.)
        - 모두 끝났지만 실패율이 기준 초과 → partial_failure
        - 아직 처리 중이거나 미처리 리뷰가 있음 → in_progress
        """
        finished = coverage.succeeded + coverage.failed
        if coverage.total > 0 and finished >= coverage.total and coverage.in_progress == 0:
            if coverage.failed / coverage.total <= max_failure_rate:
                return "complete"
            return "partial_failure"
        if coverage.succeeded > 0 or coverage.failed > 0 or coverage.in_progress > 0:
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
