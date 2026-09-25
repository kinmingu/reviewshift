"""불만 이상징후 탐지: 모든 상품·모든 인접 월 쌍을 같은 규칙으로 검정합니다.

규칙(결과를 보기 전에 정함, LLM 미사용)
- 대상: 공식 7개 카테고리 상품의 저장 월 중 인접한 두 달 쌍 전부(상품당 2쌍).
- 지표: 항목별 '아쉬워요' 리뷰 비율(분모 = 그 달 분석 성공 리뷰, 표본이 있으면 표본 안).
- 검정: 비율 증가에 대한 한쪽 Fisher 정확 검정(작은 표본에서도 사용 가능).
- 다중 비교: 모든 검정에 Benjamini-Hochberg 보정(q값).
- 판정: 이상징후 = q < 0.10, 증가 10%p 이상, 대상 월 아쉬워요 3건 이상
        주의 관찰 = 보정 전 p < 0.05(이상징후 제외)
        판정 불가 = 두 달 중 한 달이라도 분석 성공 리뷰가 10건 미만
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from math import comb

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.categories import REAL_CATEGORY_KEYS
from backend.app.models import Product
from backend.app.schemas.catalog import AnomalyItem, AnomalyReport
from backend.app.services.catalog import CatalogService

METHOD_VERSION = "anomaly-fisher-bh-v1"
MIN_ANALYZED_PER_MONTH = 10
MIN_TARGET_NEGATIVE = 3
MIN_INCREASE_PP = 10.0
Q_THRESHOLD = 0.10
WATCH_P_THRESHOLD = 0.05


# === [통계 검정] ===
def fisher_increase_p(
    baseline_count: int, baseline_total: int, target_count: int, target_total: int
) -> float:
    """대상 월 비율이 기준 월보다 크다는 한쪽 Fisher 정확 검정 p값(초기하 분포 위쪽 꼬리)."""
    population = baseline_total + target_total
    successes = baseline_count + target_count
    if target_total == 0 or baseline_total == 0 or successes == 0:
        return 1.0
    denominator = comb(population, target_total)
    upper = min(successes, target_total)
    tail = sum(
        comb(successes, k) * comb(population - successes, target_total - k)
        for k in range(target_count, upper + 1)
    )
    return min(1.0, tail / denominator)


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg 보정 q값(입력 순서 유지)."""
    total = len(p_values)
    order = sorted(range(total), key=lambda index: p_values[index])
    q_values = [1.0] * total
    running = 1.0
    for rank in range(total, 0, -1):
        index = order[rank - 1]
        running = min(running, p_values[index] * total / rank)
        q_values[index] = min(1.0, running)
    return q_values


def classify_level(
    p_value: float, q_value: float, change_pp: float | None, target_count: int
) -> str | None:
    """판정 규칙: 'anomaly'(이상징후), 'watch'(주의 관찰), None(표시 안 함)."""
    change = change_pp or 0.0
    if q_value < Q_THRESHOLD and change >= MIN_INCREASE_PP and target_count >= MIN_TARGET_NEGATIVE:
        return "anomaly"
    if p_value < WATCH_P_THRESHOLD and change > 0:
        return "watch"
    return None


# 35개 상품 전체 계산은 수 초가 걸려 짧게 캐시합니다(분류 진행에 따라 2분마다 갱신).
CACHE_SECONDS = 120
_cache: tuple[float, AnomalyReport] | None = None


def cached_report(session: Session) -> AnomalyReport:
    global _cache
    now = time.monotonic()
    if _cache is None or now - _cache[0] > CACHE_SECONDS:
        _cache = (now, AnomalyService(session).report())
    return _cache[1]


@dataclass
class _Candidate:
    product: Product
    baseline_month: str
    target_month: str
    issue: object
    p_value: float
    provisional: bool


class AnomalyService:
    def __init__(
        self, session: Session, *, min_analyzed_per_month: int = MIN_ANALYZED_PER_MONTH
    ) -> None:
        self.session = session
        self.catalog = CatalogService(session)
        self.min_analyzed_per_month = min_analyzed_per_month

    def report(self, source_mode: str = "real") -> AnomalyReport:
        filters = [Product.source_mode == source_mode]
        if source_mode == "real":
            filters.append(Product.category.in_(REAL_CATEGORY_KEYS))
        products = self.session.scalars(
            select(Product).where(*filters).order_by(Product.category, Product.id)
        ).all()
        candidates: list[_Candidate] = []
        pairs_evaluated = 0
        pairs_insufficient = 0
        products_evaluable: set[str] = set()
        # === [모든 상품 × 모든 인접 월 쌍] 기간을 결과로 고르지 않습니다 ===
        for product in products:
            months = self.catalog.products.available_months(product.id)
            for baseline_month, target_month in zip(months, months[1:], strict=False):
                comparison = self.catalog.compare(product.id, target_month, baseline_month)
                coverage = comparison.coverage
                if min(coverage.baseline_succeeded, coverage.target_succeeded) < (
                    self.min_analyzed_per_month
                ):
                    pairs_insufficient += 1
                    continue
                pairs_evaluated += 1
                products_evaluable.add(product.id)
                for issue in comparison.issues:
                    if issue.polarity != "negative":
                        continue
                    candidates.append(
                        _Candidate(
                            product=product,
                            baseline_month=baseline_month,
                            target_month=target_month,
                            issue=issue,
                            p_value=fisher_increase_p(
                                issue.baseline_count,
                                issue.baseline_total,
                                issue.target_count,
                                issue.target_total,
                            ),
                            provisional=comparison.is_provisional,
                        )
                    )

        q_values = benjamini_hochberg([item.p_value for item in candidates])
        items: list[AnomalyItem] = []
        for candidate, q_value in zip(candidates, q_values, strict=True):
            issue = candidate.issue
            level = classify_level(candidate.p_value, q_value, issue.change_pp, issue.target_count)
            if level is None:
                continue
            meta = candidate.product.metadata_json
            items.append(
                AnomalyItem(
                    level=level,
                    product_id=candidate.product.id,
                    product_name_ko=meta.get("title_ko"),
                    category=candidate.product.category,
                    image_url=candidate.product.image_url,
                    baseline_month=candidate.baseline_month,
                    target_month=candidate.target_month,
                    aspect=issue.aspect,
                    detail_label=issue.detail_label,
                    detail_name_ko=issue.detail_name_ko,
                    baseline_count=issue.baseline_count,
                    baseline_total=issue.baseline_total,
                    target_count=issue.target_count,
                    target_total=issue.target_total,
                    baseline_rate=issue.baseline_rate,
                    target_rate=issue.target_rate,
                    change_pp=issue.change_pp,
                    p_value=round(candidate.p_value, 5),
                    q_value=round(q_value, 5),
                    is_provisional=candidate.provisional,
                    evidence_review_ids=issue.evidence_review_ids[:5],
                )
            )
        items.sort(key=lambda item: (item.level != "anomaly", item.q_value, -(item.change_pp or 0)))
        return AnomalyReport(
            method_version=METHOD_VERSION,
            method=(
                "모든 상품의 인접 두 달마다 항목별 아쉬워요 비율 증가를 한쪽 Fisher 정확 검정으로 "
                "판정하고 Benjamini-Hochberg로 보정. 이상징후: q<0.10·증가 10%p 이상·대상 월 3건 이상. "
                "주의 관찰: 보정 전 p<0.05. 분석 10건 미만인 달은 판정하지 않음."
            ),
            products_total=len(products),
            products_evaluable=len(products_evaluable),
            pairs_evaluated=pairs_evaluated,
            pairs_insufficient=pairs_insufficient,
            tests=len(candidates),
            items=items,
        )
