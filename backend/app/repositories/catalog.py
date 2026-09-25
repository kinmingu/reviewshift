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
        # DB 세션 시간대와 무관하게 API의 UTC [월초, 다음 월초) 경계와 같은 월로 묶습니다.
        month = func.to_char(
            func.date_trunc("month", func.timezone("UTC", Review.reviewed_at)), "YYYY-MM"
        )
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


@dataclass(frozen=True)
class LabelExample:
    review_id: str
    rating: int
    reviewed_at: datetime
    evidence_span: str


@dataclass(frozen=True)
class MonthlyAnalysisAggregate:
    month: str
    succeeded: int
    positive_reviews: int
    negative_reviews: int


# === [상품 리뷰 리포트 집계] 상세 화면용 상품 전체 기간 집계입니다. 모든 수치는 SQL로 계산합니다 ===
class ProductInsightRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def rating_distribution(self, product_id: str) -> dict[int, int]:
        rows = self.session.execute(
            select(Review.rating, func.count(Review.id))
            .where(Review.product_id == product_id, Review.eligible.is_(True))
            .group_by(Review.rating)
        ).all()
        counts = {rating: 0 for rating in range(1, 6)}
        counts.update({int(rating): int(count) for rating, count in rows})
        return counts

    def _succeeded_reviews(self, product_id: str, run_id: str):
        """활성 run에서 분류에 성공한 적격 리뷰 조건(비율의 분모)입니다."""
        return (
            select(Review.id)
            .join(ReviewAnalysisResult, ReviewAnalysisResult.review_id == Review.id)
            .where(
                Review.product_id == product_id,
                Review.eligible.is_(True),
                ReviewAnalysisResult.run_id == run_id,
                ReviewAnalysisResult.status == "succeeded",
            )
        )

    def succeeded_count(self, product_id: str, run_id: str) -> int:
        succeeded = self._succeeded_reviews(product_id, run_id).subquery()
        return int(self.session.scalar(select(func.count()).select_from(succeeded)) or 0)

    def polarity_review_counts(self, product_id: str, run_id: str) -> dict[str, int]:
        """극성별로 해당 라벨이 하나 이상 있는 고유 리뷰 수입니다."""
        succeeded = self._succeeded_reviews(product_id, run_id).subquery()
        rows = self.session.execute(
            select(ReviewLabel.polarity, func.count(distinct(ReviewLabel.review_id)))
            .where(
                ReviewLabel.run_id == run_id,
                ReviewLabel.review_id.in_(select(succeeded.c.id)),
            )
            .group_by(ReviewLabel.polarity)
        ).all()
        return {str(polarity): int(count) for polarity, count in rows}

    def label_counts(self, product_id: str, run_id: str) -> list[tuple[str, str, str, int]]:
        succeeded = self._succeeded_reviews(product_id, run_id).subquery()
        rows = self.session.execute(
            select(
                ReviewLabel.aspect,
                ReviewLabel.detail_label,
                ReviewLabel.polarity,
                func.count(distinct(ReviewLabel.review_id)),
            )
            .where(
                ReviewLabel.run_id == run_id,
                ReviewLabel.review_id.in_(select(succeeded.c.id)),
            )
            .group_by(ReviewLabel.aspect, ReviewLabel.detail_label, ReviewLabel.polarity)
        ).all()
        return [(str(a), str(d), str(p), int(c)) for a, d, p, c in rows]

    def mention_counts(self, product_id: str, run_id: str) -> dict[tuple[str, str], int]:
        """항목을 한 번이라도 언급한 고유 리뷰 수(극성 무관)입니다."""
        succeeded = self._succeeded_reviews(product_id, run_id).subquery()
        rows = self.session.execute(
            select(
                ReviewLabel.aspect,
                ReviewLabel.detail_label,
                func.count(distinct(ReviewLabel.review_id)),
            )
            .where(
                ReviewLabel.run_id == run_id,
                ReviewLabel.review_id.in_(select(succeeded.c.id)),
            )
            .group_by(ReviewLabel.aspect, ReviewLabel.detail_label)
        ).all()
        return {(str(a), str(d)): int(c) for a, d, c in rows}

    def label_examples(
        self,
        product_id: str,
        run_id: str,
        aspect: str,
        detail_label: str,
        polarity: str,
        limit: int,
    ) -> list[LabelExample]:
        succeeded = self._succeeded_reviews(product_id, run_id).subquery()
        rows = self.session.execute(
            select(Review.id, Review.rating, Review.reviewed_at, ReviewLabel.evidence_span)
            .join(ReviewLabel, ReviewLabel.review_id == Review.id)
            .where(
                ReviewLabel.run_id == run_id,
                ReviewLabel.aspect == aspect,
                ReviewLabel.detail_label == detail_label,
                ReviewLabel.polarity == polarity,
                Review.id.in_(select(succeeded.c.id)),
            )
            .order_by(Review.reviewed_at.desc(), Review.id, ReviewLabel.id)
        ).all()
        examples: list[LabelExample] = []
        seen: set[str] = set()
        for review_id, rating, reviewed_at, evidence in rows:
            # 같은 리뷰의 근거가 여러 개여도 대표 예시에는 리뷰당 한 번만 넣습니다.
            if review_id in seen:
                continue
            seen.add(review_id)
            examples.append(LabelExample(review_id, int(rating), reviewed_at, evidence))
            if len(examples) >= limit:
                break
        return examples

    def monthly_analysis(self, product_id: str, run_id: str) -> list[MonthlyAnalysisAggregate]:
        month = func.to_char(
            func.date_trunc("month", func.timezone("UTC", Review.reviewed_at)), "YYYY-MM"
        )
        succeeded_rows = dict(
            self.session.execute(
                select(month, func.count(distinct(Review.id)))
                .join(ReviewAnalysisResult, ReviewAnalysisResult.review_id == Review.id)
                .where(
                    Review.product_id == product_id,
                    Review.eligible.is_(True),
                    ReviewAnalysisResult.run_id == run_id,
                    ReviewAnalysisResult.status == "succeeded",
                )
                .group_by(month)
            ).all()
        )
        polarity_rows = self.session.execute(
            select(month, ReviewLabel.polarity, func.count(distinct(Review.id)))
            .join(ReviewLabel, ReviewLabel.review_id == Review.id)
            .join(
                ReviewAnalysisResult,
                (ReviewAnalysisResult.review_id == Review.id)
                & (ReviewAnalysisResult.run_id == ReviewLabel.run_id),
            )
            .where(
                Review.product_id == product_id,
                Review.eligible.is_(True),
                ReviewLabel.run_id == run_id,
                ReviewAnalysisResult.status == "succeeded",
                ReviewLabel.polarity.in_(("positive", "negative")),
            )
            .group_by(month, ReviewLabel.polarity)
        ).all()
        by_month: dict[str, dict[str, int]] = {}
        for value_month, polarity, count in polarity_rows:
            by_month.setdefault(str(value_month), {})[str(polarity)] = int(count)
        return [
            MonthlyAnalysisAggregate(
                month=str(value_month),
                succeeded=int(count),
                positive_reviews=by_month.get(str(value_month), {}).get("positive", 0),
                negative_reviews=by_month.get(str(value_month), {}).get("negative", 0),
            )
            for value_month, count in sorted(succeeded_rows.items())
        ]


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
