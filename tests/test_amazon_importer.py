from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.app.importers.amazon_reviews import (
    normalized_rating,
    review_identity,
    source_record_key,
    timestamp_ms_to_utc,
)
from scripts.amazon_reviews_source import REVIEW_FILES
from scripts.import_amazon_appliances import selected_review_rows


def _record(timestamp: int, *, text: str = "actual review") -> dict:
    return {
        "rating": 5.0,
        "title": "title",
        "text": text,
        "asin": "VARIANT1",
        "parent_asin": "PARENT1",
        "user_id": "USER1",
        "timestamp": timestamp,
    }


def test_timestamp_is_milliseconds_and_month_boundaries_are_utc() -> None:
    assert timestamp_ms_to_utc(1_609_459_200_000) == datetime(
        2021, 1, 1, tzinfo=timezone.utc
    )
    assert timestamp_ms_to_utc(1_612_137_599_999).strftime("%Y-%m") == "2021-01"
    assert timestamp_ms_to_utc(1_612_137_600_000).strftime("%Y-%m") == "2021-02"


def test_review_identity_is_stable_and_rating_must_be_integral() -> None:
    record = _record(1_609_459_200_000)
    assert review_identity(record) == review_identity(dict(record))
    assert source_record_key(review_identity(record)).startswith("amazon-reviews-2023:")
    assert normalized_rating(5.0) == 5
    with pytest.raises(ValueError):
        normalized_rating(4.5)


def test_selected_rows_exclude_duplicates_ineligible_and_outside_month(tmp_path) -> None:
    january_start = _record(1_609_459_200_000)
    january_end = _record(1_612_137_599_999)
    january_end["user_id"] = "USER2"
    february_start = _record(1_612_137_600_000)
    february_start["user_id"] = "USER3"
    missing_text = _record(1_610_000_000_000, text="")
    missing_text["user_id"] = "USER4"
    partitions = [
        [january_start, january_end, february_start, missing_text],
        [dict(january_start)],
    ]
    for remote_file, records in zip(REVIEW_FILES, partitions, strict=True):
        path = tmp_path / remote_file.path
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(records), path)

    rows, audit = selected_review_rows(
        tmp_path,
        {
            "PARENT1": {
                "import_start_month": "2021-01",
                "import_end_month": "2021-01",
            }
        },
    )
    assert len(rows) == 2
    assert audit == {
        "selected_source_rows": 5,
        "excluded_outside_period": 1,
        "excluded_ineligible": 1,
        "excluded_duplicate": 1,
        "eligible_unique_import_rows": 2,
    }
