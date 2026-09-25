import json
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
from scripts import import_amazon_category
from scripts.amazon_category_sources import RemoteParquet
from scripts.import_amazon_category import load_selection, validate_selected_counts


# === [원천 레코드 규칙] timestamp 단위·월 경계, 중복 판별 키 ===
def _record(timestamp: int, *, user_id: str = "USER1", text: str = "actual review") -> dict:
    return {
        "rating": 5.0,
        "title": "title",
        "text": text,
        "asin": "VARIANT1",
        "parent_asin": "PARENT1",
        "user_id": user_id,
        "timestamp": timestamp,
    }


def test_timestamp_is_milliseconds_and_month_boundaries_are_utc() -> None:
    assert timestamp_ms_to_utc(1_609_459_200_000) == datetime(2021, 1, 1, tzinfo=timezone.utc)
    assert timestamp_ms_to_utc(1_612_137_599_999).strftime("%Y-%m") == "2021-01"
    assert timestamp_ms_to_utc(1_612_137_600_000).strftime("%Y-%m") == "2021-02"


def test_review_identity_is_stable_and_rating_must_be_integral() -> None:
    record = _record(1_609_459_200_000)
    assert review_identity(record) == review_identity(dict(record))
    assert source_record_key(review_identity(record)).startswith("amazon-reviews-2023:")
    assert normalized_rating(5.0) == 5
    with pytest.raises(ValueError):
        normalized_rating(4.5)


# === [선택 기간 적재] 기간 밖·부적격·정확 중복 제외 ===
def test_selected_rows_exclude_duplicates_ineligible_and_outside_period(
    tmp_path, monkeypatch
) -> None:
    january = _record(1_609_459_200_000)
    february = _record(1_612_137_600_000, user_id="USER2")
    april = _record(1_617_235_200_000, user_id="USER3")  # 2021-04: 선택 기간 밖
    missing_text = _record(1_610_000_000_000, user_id="USER4", text="  ")
    same_text_other_user = _record(1_609_459_200_000, user_id="USER5")
    partitions = [
        [january, february, april, missing_text],
        [dict(january), same_text_other_user],  # 파일이 달라도 정확 중복은 1건으로 봅니다.
    ]
    remote_files = []
    for index, records in enumerate(partitions):
        path = f"raw_review_Electronics/part-{index}.parquet"
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(records), tmp_path / path)
        remote_files.append(RemoteParquet(path=path, size=0, revision="test", sha256=None))
    monkeypatch.setattr(import_amazon_category, "list_remote_files", lambda *_: remote_files)

    rows, audit, monthly = import_amazon_category.selected_review_rows(
        "Electronics", tmp_path, {"PARENT1": {"months": ["2021-01", "2021-02", "2021-03"]}}
    )

    assert len(rows) == 3
    assert audit == {
        "selected_source_rows": 6,
        "excluded_outside_period": 1,
        "excluded_ineligible": 1,
        "excluded_exact_duplicate": 1,
        "eligible_unique_import_rows": 3,
    }
    # 문구가 같아도 다른 사용자의 리뷰는 중복으로 제거하지 않습니다.
    assert monthly == {"PARENT1": {"2021-01": 2, "2021-02": 1}}


# === [상품 선정 파일 검증] ===


def test_load_selection_requires_two_products_and_three_consecutive_months(tmp_path):
    path = tmp_path / "selection.json"
    path.write_text(
        json.dumps(
            {
                "categories": {
                    "Electronics": {
                        "products": [
                            {
                                "parent_asin": "PARENT-1",
                                "months": ["2022-11", "2022-12", "2023-01"],
                            },
                            {
                                "parent_asin": "PARENT-2",
                                "months": ["2023-01", "2023-02", "2023-03"],
                            },
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    selected = load_selection(path, "Electronics")
    assert set(selected) == {"PARENT-1", "PARENT-2"}


def test_load_selection_rejects_non_consecutive_months(tmp_path):
    path = tmp_path / "selection.json"
    path.write_text(
        json.dumps(
            {
                "categories": {
                    "Electronics": {
                        "products": [
                            {
                                "parent_asin": "PARENT-1",
                                "months": ["2023-01", "2023-03", "2023-04"],
                            },
                            {
                                "parent_asin": "PARENT-2",
                                "months": ["2023-01", "2023-02", "2023-03"],
                            },
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="연속된 3개월"):
        load_selection(path, "Electronics")


def test_validate_selected_counts_enforces_each_month_and_total():
    selected = {
        "PARENT-1": {"months": ["2023-01", "2023-02", "2023-03"]},
        "PARENT-2": {"months": ["2023-01", "2023-02", "2023-03"]},
    }
    monthly = {
        "PARENT-1": {"2023-01": 50, "2023-02": 60, "2023-03": 70},
        "PARENT-2": {"2023-01": 80, "2023-02": 90, "2023-03": 100},
    }
    validate_selected_counts(selected, monthly)

    monthly["PARENT-2"]["2023-02"] = 29
    with pytest.raises(ValueError, match="30건 미만"):
        validate_selected_counts(selected, monthly)
