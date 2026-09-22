from sqlalchemy.orm import Session

from backend.app.models import Product, Review
from backend.app.repositories.catalog import (
    AnalysisRunRepository,
    ProductRepository,
    ReviewRepository,
)
from backend.app.schemas.catalog import (
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
        return self.products.categories(source_mode)

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
        if product.source_mode == "real":
            return ComparisonResponse(
                product_id=product_id,
                target_month=target_month,
                baseline_month=baseline_month,
                source_mode="real",
                coverage=CoverageResponse(
                    target_total=target_total,
                    target_labeled=0,
                    baseline_total=baseline_total,
                    baseline_labeled=0,
                    target_average_rating=target_average_rating,
                    baseline_average_rating=baseline_average_rating,
                ),
                status="insufficient_data",
                issues=[],
                data_version=str(
                    product.metadata_json.get("review_revision", "amazon-reviews-2023")
                ),
                analysis_version="not-analyzed",
            )

        run = self.runs.latest_completed()
        if run is None:
            raise AnalysisRunUnavailableError("no completed analysis run")

        target_labeled = self.reviews.count_labeled(
            product_id, target_start, target_end, run.id
        )
        baseline_labeled = self.reviews.count_labeled(
            product_id, baseline_start, baseline_end, run.id
        )
        coverage = CoverageResponse(
            target_total=target_total,
            target_labeled=target_labeled,
            baseline_total=baseline_total,
            baseline_labeled=baseline_labeled,
            target_average_rating=target_average_rating,
            baseline_average_rating=baseline_average_rating,
        )

        complete = (
            target_total > 0
            and baseline_total > 0
            and target_labeled == target_total
            and baseline_labeled == baseline_total
        )
        issues: list[ComparisonIssue] = []
        if complete:
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
                target_rate = target_count / target_total
                baseline_rate = baseline_count / baseline_total
                evidence_ids = sorted(
                    set(target_item.review_ids if target_item else ())
                    | set(baseline_item.review_ids if baseline_item else ())
                )
                issues.append(
                    ComparisonIssue(
                        aspect=key[0],
                        detail_label=key[1],
                        polarity=key[2],
                        target_count=target_count,
                        target_total=target_total,
                        target_rate=target_rate,
                        baseline_count=baseline_count,
                        baseline_total=baseline_total,
                        baseline_rate=baseline_rate,
                        change_pp=(target_rate - baseline_rate) * 100,
                        evidence_review_ids=evidence_ids,
                    )
                )
            issues.sort(
                key=lambda item: (
                    -abs(item.change_pp),
                    item.aspect,
                    item.detail_label,
                    item.polarity,
                )
            )

        return ComparisonResponse(
            product_id=product_id,
            target_month=target_month,
            baseline_month=baseline_month,
            source_mode=product.source_mode,
            coverage=coverage,
            status="ok" if complete else "insufficient_data",
            issues=issues,
            data_version=run.data_version,
            analysis_version=run.id,
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
        start, end = month_bounds(month)
        reviews, total = self.reviews.list(
            product_id=product_id,
            start=start,
            end=end,
            aspect=aspect,
            polarity=polarity,
            page=page,
            page_size=page_size,
        )
        return [self._review_response(review) for review in reviews], total, product.source_mode

    def _require_product(self, product_id: str) -> Product:
        product = self.products.get(product_id)
        if product is None:
            raise ProductNotFoundError(product_id)
        return product

    def _summary(self, product: Product) -> ProductSummary:
        return ProductSummary(
            id=product.id,
            title=product.title,
            category=product.category,
            image_url=product.image_url,
            review_count=self.products.review_count(product.id),
            available_months=self.products.available_months(product.id),
            source_mode=product.source_mode,
        )

    @staticmethod
    def _review_response(review: Review) -> ReviewResponse:
        labels = [
            ReviewLabelResponse(
                aspect=label.aspect,
                detail_label=label.detail_label,
                polarity=label.polarity,
                evidence_span=label.evidence_span,
                analysis_version=label.run_id,
            )
            for label in sorted(
                review.labels,
                key=lambda item: (item.aspect, item.detail_label, item.polarity, item.id),
            )
        ]
        return ReviewResponse(
            id=review.id,
            title=review.title,
            text=review.text,
            rating=review.rating,
            reviewed_at=review.reviewed_at,
            labels=labels,
            source_mode=review.source_mode,
        )
