from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.profile_amazon_category import (
    count_candidate_months,
    count_products,
    rank_windows,
    shift_month,
)


def _timestamp_ms(year: int, month: int) -> int:
    return int(datetime(year, month, 15, tzinfo=timezone.utc).timestamp() * 1000)


def test_profile_counts_only_eligible_rows_and_finds_three_month_window(tmp_path):
    rows = []
    for month in (1, 2, 3):
        rows.extend(
            {
                "rating": 5.0,
                "text": f"real review {month}-{index}",
                "asin": "CHILD-1",
                "parent_asin": "PARENT-1",
                "timestamp": _timestamp_ms(2023, month),
            }
            for index in range(50)
        )
    # 마지막 관측 월은 완료되지 않은 달로 취급하므로 후보 구간에 포함하지 않습니다.
    rows.append(
        {
            "rating": 4.0,
            "text": "partial latest month",
            "asin": "CHILD-1",
            "parent_asin": "PARENT-1",
            "timestamp": _timestamp_ms(2023, 4),
        }
    )
    rows.append(
        {
            "rating": 1.0,
            "text": "   ",
            "asin": "CHILD-1",
            "parent_asin": "PARENT-1",
            "timestamp": _timestamp_ms(2023, 3),
        }
    )
    path = tmp_path / "reviews.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path)

    totals, audit = count_products([path], batch_size=32)
    assert totals["PARENT-1"] == 151
    assert audit["invalid_text"] == 1
    assert audit["eligible_rows"] == 151
    assert audit["last_observed_month"] == "2023-04"

    monthly = count_candidate_months([path], {"PARENT-1"}, batch_size=32)
    candidates = rank_windows(monthly, str(audit["last_observed_month"]))
    assert candidates == [
        {
            "parent_asin": "PARENT-1",
            "months": ["2023-01", "2023-02", "2023-03"],
            "monthly_counts": {"2023-01": 50, "2023-02": 50, "2023-03": 50},
            "review_count": 150,
            "balance_gap": 0,
        }
    ]


def test_shift_month_crosses_year_boundary():
    assert shift_month("2023-01", -2) == "2022-11"
    assert shift_month("2023-12", 1) == "2024-01"
