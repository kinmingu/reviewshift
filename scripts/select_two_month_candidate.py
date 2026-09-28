"""초기 두 달 비교 데모에 쓸 상품 후보를 SQL로 찾는 스크립트."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from backend.app.core.database import SessionLocal

QUERY = text(
    """
    WITH monthly AS (
        SELECT
            p.id AS product_id,
            p.category,
            p.title,
            p.metadata_json ->> 'title_ko' AS title_ko,
            date_trunc('month', r.reviewed_at) AS month_start,
            count(*)::integer AS review_count
        FROM products p
        JOIN reviews r ON r.product_id = p.id
        WHERE p.source_mode = 'real' AND r.source_mode = 'real' AND r.eligible
          AND p.category IN (
              'Electronics', 'Beauty_and_Personal_Care',
              'Cell_Phones_and_Accessories', 'Home_and_Kitchen',
              'Sports_and_Outdoors', 'Toys_and_Games',
              'Health_and_Household'
          )
        GROUP BY p.id, p.category, p.title, p.metadata_json ->> 'title_ko', month_start
    ), pairs AS (
        SELECT
            newer.product_id,
            newer.category,
            newer.title,
            newer.title_ko,
            to_char(older.month_start, 'YYYY-MM') AS baseline_month,
            older.review_count AS baseline_count,
            to_char(newer.month_start, 'YYYY-MM') AS target_month,
            newer.review_count AS target_count,
            older.review_count + newer.review_count AS total_count
        FROM monthly newer
        JOIN monthly older
          ON older.product_id = newer.product_id
         AND newer.month_start = older.month_start + interval '1 month'
        WHERE older.review_count >= 30 AND newer.review_count >= 30
    )
    SELECT *
    FROM pairs
    ORDER BY total_count, product_id, baseline_month
    """
)


# 조건에 맞는 후보 상품 목록을 DB에서 가져옵니다.
def candidates() -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.execute(QUERY).mappings().all()
    return [dict(row) for row in rows]


if __name__ == "__main__":
    values = candidates()
    print(
        json.dumps(
            {"selection_rule": "인접한 두 달 모두 30건 이상 중 합계 최소", "items": values},
            ensure_ascii=False,
            indent=2,
        )
    )
