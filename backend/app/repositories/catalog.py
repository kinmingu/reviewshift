from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, distinct, func, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.app.core.categories import REAL_CATEGORY_KEYS
from backend.app.models import (
    AnalysisRun,
    Product,
    Review,
    ReviewAnalysisResult,
    ReviewLabel,
)


@dataclass(frozen=True)
class LabelAggregate:
    aspect: str
    detail_label: str
    polarity: str
    count: int
    review_ids: tuple[str, ...]


@dataclass(frozen=True)
class MonthlyReviewAggregate:
    month: str
    review_count: int
    average_rating: float


@dataclass(frozen=True)
class AnalysisCoverageAggregate:
    total: int
    succeeded: int
    failed: int
    in_progress: int
    labeled: int


class ProductRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def categories(self, source_mode: str) -> list[str]:
        return list(
            self.session.scalars(
                select(Product.category)
                .where(Product.source_mode == source_mode)
                .distinct()
                .order_by(Product.category)
            )
        )

    def list(
        self,
        *,
        query: str | None,
        category: str | None,
        source_mode: str,
        page: int,
        page_size: int,
    ) -> tuple[list[Product], int]:
        filters = [Product.source_mode == source_mode]
        # 기존 Appliances 데이터는 보존하지만, 공식 7개 카테고리 기본 목록(14개 목표)에는 섞지 않습니다.
        if source_mode == "real" and not category:
            filters.append(Product.category.in_(REAL_CATEGORY_KEYS))
        if query:
            pattern = f"%{query.strip()}%"
            # 원문명은 그대로 보존하고, 별도 메타데이터의 한국어 표시명도 같은 검색창에서 찾습니다.
            filters.append(
                or_(
                    Product.title.ilike(pattern),
                    Product.metadata_json["title_ko"].as_string().ilike(pattern),
                    Product.parent_asin.ilike(pattern),
                )
            )
        if category:
            filters.append(Product.category == category)

        base: Select[tuple[Product]] = select(Product).where(*filters)
        total = self.session.scalar(
            select(func.count()).select_from(base.order_by(None).subquery())
        ) or 0
        items = list(
            self.session.scalars(
                base.order_by(Product.title).offset((page - 1) * page_size).limit(page_size)
            )
        )
        return items, total

    def get(self, product_id: str) -> Product | None:
        return self.session.get(Product, product_id)

    def review_count(self, product_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count(Review.id)).where(
                    Review.product_id == product_id, Review.eligible.is_(True)
                )
            )
            or 0
        )

    def available_months(self, product_id: str) -> list[str]:
        return [item.month for item in self.monthly_stats(product_id)]

    def monthly_stats(self, product_id: str) -> list[MonthlyReviewAggregate]:
        month = func.to_char(func.date_trunc("month", Review.reviewed_at), "YYYY-MM")
        rows = self.session.execute(
            select(month, func.count(Review.id), func.avg(Review.rating))
                .where(Review.product_id == product_id, Review.eligible.is_(True))
                .group_by(month)
                .order_by(month)
        ).all()
        return [
            MonthlyReviewAggregate(
                month=row[0], review_count=int(row[1]), average_rating=float(row[2])
            )
            for row in rows
        ]


class ReviewRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def count_eligible(self, product_id: str, start: datetime, end: datetime) -> int:
        return int(
            self.session.scalar(
                select(func.count(Review.id)).where(
                    Review.product_id == product_id,
                    Review.eligible.is_(True),
                    Review.reviewed_at >= start,
                    Review.reviewed_at < end,
                )
            )
            or 0
        )

    def average_rating(
        self, product_id: str, start: datetime, end: datetime
    ) -> float | None:
        value = self.session.scalar(
            select(func.avg(Review.rating)).where(
                Review.product_id == product_id,
                Review.eligible.is_(True),
                Review.reviewed_at >= start,
                Review.reviewed_at < end,
            )
        )
        return float(value) if value is not None else None

    def count_labeled(
        self, product_id: str, start: datetime, end: datetime, run_id: str
    ) -> int:
        return int(
            self.session.scalar(
                select(func.count(distinct(Review.id)))
                .join(ReviewLabel, ReviewLabel.review_id == Review.id)
                .where(
                    Review.product_id == product_id,
                    Review.eligible.is_(True),
                    Review.reviewed_at >= start,
                    Review.reviewed_at < end,
                    ReviewLabel.run_id == run_id,
                )
            )
            or 0
        )

    def analysis_coverage(
        self,
        product_id: str,
        start: datetime,
        end: datetime,
        run_id: str,
    ) -> AnalysisCoverageAggregate:
        total = self.count_eligible(product_id, start, end)
        status_rows = dict(
            self.session.execute(
                select(ReviewAnalysisResult.status, func.count(ReviewAnalysisResult.id))
                .join(Review, Review.id == ReviewAnalysisResult.review_id)
                .where(
                    Review.product_id == product_id,
                    Review.eligible.is_(True),
                    Review.reviewed_at >= start,
                    Review.reviewed_at < end,
                    ReviewAnalysisResult.run_id == run_id,
                )
                .group_by(ReviewAnalysisResult.status)
            ).all()
        )
        return AnalysisCoverageAggregate(
            total=total,
            succeeded=int(status_rows.get("succeeded", 0)),
            failed=int(status_rows.get("failed", 0)),
            in_progress=int(status_rows.get("pending", 0))
            + int(status_rows.get("running", 0)),
            labeled=self.count_labeled(product_id, start, end, run_id),
        )

    def label_aggregates(
        self, product_id: str, start: datetime, end: datetime, run_id: str
    ) -> list[LabelAggregate]:
        rows = self.session.execute(
            select(
                ReviewLabel.aspect,
                ReviewLabel.detail_label,
                ReviewLabel.polarity,
                func.count(distinct(Review.id)),
                func.array_agg(distinct(Review.id)),
            )
            .join(Review, Review.id == ReviewLabel.review_id)
            .join(
                ReviewAnalysisResult,
                (ReviewAnalysisResult.review_id == Review.id)
                & (ReviewAnalysisResult.run_id == ReviewLabel.run_id),
            )
            .where(
                Review.product_id == product_id,
                Review.eligible.is_(True),
                Review.reviewed_at >= start,
                Review.reviewed_at < end,
                ReviewLabel.run_id == run_id,
                ReviewAnalysisResult.status == "succeeded",
            )
            .group_by(
                ReviewLabel.aspect, ReviewLabel.detail_label, ReviewLabel.polarity
            )
        ).all()
        return [
            LabelAggregate(
                aspect=row[0],
                detail_label=row[1],
                polarity=row[2],
                count=int(row[3]),
                review_ids=tuple(sorted(row[4] or [])),
            )
            for row in rows
        ]

    def list(
        self,
        *,
        product_id: str,
        start: datetime,
        end: datetime,
        aspect: str | None,
        polarity: str | None,
        run_id: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Review], int]:
        query = select(Review).where(
            Review.product_id == product_id,
            Review.eligible.is_(True),
            Review.reviewed_at >= start,
            Review.reviewed_at < end,
        )
        if aspect or polarity:
            if run_id is None:
                return [], 0
            query = query.join(ReviewLabel, ReviewLabel.review_id == Review.id)
            query = query.where(ReviewLabel.run_id == run_id)
            if aspect:
                query = query.where(ReviewLabel.aspect == aspect)
            if polarity:
                query = query.where(ReviewLabel.polarity == polarity)
            query = query.distinct()

        total = int(
            self.session.scalar(
                select(func.count()).select_from(query.order_by(None).subquery())
            )
            or 0
        )
        items = list(
            self.session.scalars(
                query.options(
                    selectinload(Review.labels).selectinload(ReviewLabel.run),
                    selectinload(Review.analysis_results),
                )
                .order_by(Review.reviewed_at.desc(), Review.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).unique()
        )
        return items, total


class AnalysisRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def active(self, source_mode: str) -> AnalysisRun | None:
        return self.session.scalar(
            select(AnalysisRun)
            .where(
                AnalysisRun.source_mode == source_mode,
                AnalysisRun.is_active.is_(True),
            )
            .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
            .limit(1)
        )
