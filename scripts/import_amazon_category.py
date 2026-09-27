from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.app.core.database import SessionLocal
from backend.app.importers.amazon_reviews import (
    SOURCE_NAME,
    is_eligible_review,
    product_id,
    review_id,
    review_identity,
    source_record_key,
    timestamp_ms_to_utc,
)
from backend.app.models import Product, Review
from scripts.amazon_category_sources import CATEGORY_SOURCES, list_remote_files
from scripts.profile_amazon_category import shift_month

DEFAULT_INPUT = Path("data/raw/amazon_reviews_2023")
DEFAULT_SELECTION = Path("config/amazon_category_selection.json")
DEFAULT_REPORT = Path("data/processed")
# 카테고리별 제품 수. 제품마다 AI 분석 표본 수(analysis_sample_size)만 다르게 둡니다.
PRODUCTS_PER_CATEGORY = 8
REVIEW_COLUMNS = [
    "rating",
    "title",
    "text",
    "asin",
    "parent_asin",
    "user_id",
    "timestamp",
]
METADATA_COLUMNS = [
    "parent_asin",
    "title",
    "main_category",
    "average_rating",
    "rating_number",
    "store",
    "images",
    "description",
    "features",
]


def _first_image(images: Any) -> str | None:
    if not isinstance(images, dict):
        return None
    for size in ("hi_res", "large", "thumb"):
        for value in images.get(size) or []:
            if value:
                return str(value)
    return None


def _description(value: Any) -> str | None:
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(cleaned) or None
    cleaned = str(value or "").strip()
    return cleaned or None


def load_selection(path: Path, category: str) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    category_payload = payload.get("categories", {}).get(category)
    if category_payload is None:
        raise ValueError(f"선정 파일에 {category} 항목이 없습니다.")
    products = category_payload.get("products", [])
    if len(products) != PRODUCTS_PER_CATEGORY:
        raise ValueError(f"{category}에는 정확히 제품 {PRODUCTS_PER_CATEGORY}개가 필요합니다.")

    selected = {str(item["parent_asin"]): item for item in products}
    if len(selected) != PRODUCTS_PER_CATEGORY:
        raise ValueError("parent_asin은 서로 달라야 합니다.")
    for parent_asin, item in selected.items():
        months = item.get("months", [])
        if len(months) != 3 or any(
            months[index] != shift_month(months[0], index) for index in range(3)
        ):
            raise ValueError(f"{parent_asin}: 정확히 연속된 3개월이 필요합니다.")
        sample_size = item.get("analysis_sample_size")
        if sample_size is not None and (not isinstance(sample_size, int) or sample_size < 1):
            raise ValueError(f"{parent_asin}: analysis_sample_size는 1 이상의 정수여야 합니다.")
    return selected


def read_metadata(
    category: str, input_root: Path, selected_ids: set[str]
) -> dict[str, dict[str, Any]]:
    source = CATEGORY_SOURCES[category]
    candidate_values = list(selected_ids)
    result: dict[str, dict[str, Any]] = {}
    for remote_file in list_remote_files(source, "metadata"):
        path = input_root / remote_file.path
        if not path.exists():
            raise FileNotFoundError(path)
        for batch in pq.ParquetFile(path).iter_batches(
            batch_size=32_768, columns=METADATA_COLUMNS
        ):
            parent = batch.column(batch.schema.get_field_index("parent_asin"))
            mask = pc.fill_null(
                pc.is_in(parent, value_set=pa.array(candidate_values)), False
            )
            if not bool(pc.any(mask).as_py()):
                continue
            for row in batch.filter(mask).to_pylist():
                if str(row.get("title") or "").strip():
                    result[row["parent_asin"]] = row
    missing = selected_ids - result.keys()
    if missing:
        raise ValueError(f"선정 상품 메타데이터가 없습니다: {sorted(missing)}")
    return result


def selected_review_rows(
    category: str, input_root: Path, selected: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, dict[str, int]]]:
    source = CATEGORY_SOURCES[category]
    rows: dict[str, dict[str, Any]] = {}
    monthly: dict[str, Counter[str]] = {
        parent_asin: Counter() for parent_asin in selected
    }
    audit = Counter()
    selected_ids = set(selected)

    for remote_file in list_remote_files(source, "reviews"):
        path = input_root / remote_file.path
        if not path.exists():
            raise FileNotFoundError(path)
        for batch in pq.ParquetFile(path).iter_batches(
            batch_size=65_536, columns=REVIEW_COLUMNS
        ):
            # parent_asin으로 먼저 줄여야 4천만 건 전체를 Python 객체로 만들지 않습니다.
            parent = batch.column(batch.schema.get_field_index("parent_asin"))
            mask = pc.fill_null(
                pc.is_in(parent, value_set=pa.array(list(selected_ids))), False
            )
            if not bool(pc.any(mask).as_py()):
                continue
            for record in batch.filter(mask).to_pylist():
                parent_asin = record["parent_asin"]
                audit["selected_source_rows"] += 1
                if not is_eligible_review(record):
                    audit["excluded_ineligible"] += 1
                    continue
                month = timestamp_ms_to_utc(record["timestamp"]).strftime("%Y-%m")
                if month not in selected[parent_asin]["months"]:
                    audit["excluded_outside_period"] += 1
                    continue
                identity = review_identity(record)
                key = source_record_key(identity)
                if key in rows:
                    audit["excluded_exact_duplicate"] += 1
                    continue
                rows[key] = {
                    "id": review_id(identity),
                    "product_id": product_id(parent_asin),
                    "source_record_key": key,
                    "source_mode": "real",
                    "asin": str(record["asin"]),
                    "title": str(record.get("title") or "").strip() or None,
                    "text": str(record["text"]).strip(),
                    "rating": int(record["rating"]),
                    "reviewed_at": timestamp_ms_to_utc(record["timestamp"]),
                    "eligible": True,
                }
                monthly[parent_asin][month] += 1

    audit["eligible_unique_import_rows"] = len(rows)
    monthly_result = {
        parent_asin: dict(sorted(counts.items())) for parent_asin, counts in monthly.items()
    }
    return list(rows.values()), dict(audit), monthly_result


def validate_selected_counts(
    selected: dict[str, dict[str, Any]], monthly: dict[str, dict[str, int]]
) -> None:
    for parent_asin, item in selected.items():
        counts = monthly[parent_asin]
        for month in item["months"]:
            if counts.get(month, 0) < 30:
                raise ValueError(f"{parent_asin}/{month}: 유효 리뷰가 30건 미만입니다.")
        total = sum(counts.get(month, 0) for month in item["months"])
        if not 150 <= total <= 600:
            raise ValueError(f"{parent_asin}: 선택한 3개월 리뷰 합계가 150~600 밖입니다.")


def upsert_data(
    session: Session,
    category: str,
    selected: dict[str, dict[str, Any]],
    metadata: dict[str, dict[str, Any]],
    review_rows: list[dict[str, Any]],
) -> dict[str, int]:
    source = CATEGORY_SOURCES[category]
    selected_product_ids = [product_id(value) for value in selected]
    reviews_before = int(
        session.scalar(
            select(func.count(Review.id)).where(Review.product_id.in_(selected_product_ids))
        )
        or 0
    )
    for parent_asin, selection in selected.items():
        item = metadata[parent_asin]
        values = {
            "id": product_id(parent_asin),
            "source": SOURCE_NAME,
            "source_mode": "real",
            "parent_asin": parent_asin,
            "title": str(item["title"]).strip(),
            "category": category,
            "image_url": _first_image(item.get("images")),
            "metadata_json": {
                "fixture": False,
                "source_category": category,
                "category_name_ko": source.korean_name,
                "title_ko": selection.get("title_ko"),
                "title_ko_source": selection.get("title_ko_source"),
                "description_ko": selection.get("description_ko"),
                "product_type": selection.get("product_type"),
                "main_category": item.get("main_category"),
                "store": item.get("store"),
                "description": _description(item.get("description")),
                "features": item.get("features") or [],
                "source_average_rating": item.get("average_rating"),
                "source_rating_number": item.get("rating_number"),
                "review_revision": source.reviews.revision,
                "metadata_revision": source.metadata.revision,
                "analysis_months": selection["months"],
                # AI 분석 표본 수(없으면 전체). 결과를 보기 전에 선정 파일에서 정합니다.
                "analysis_sample_size": selection.get("analysis_sample_size"),
                # 기본 비교는 인접한 마지막 두 달입니다(첫 달↔마지막 달은 가운데 달을 건너뜀).
                "baseline_month": selection["months"][-2],
                "target_month": selection["months"][-1],
            },
        }
        statement = insert(Product).values(**values).on_conflict_do_update(
            index_elements=[Product.id],
            set_={key: value for key, value in values.items() if key != "id"},
        )
        session.execute(statement)

    # source_record_key의 UNIQUE 제약과 DO NOTHING을 함께 써서 같은 원본을 재실행해도 늘지 않습니다.
    for start in range(0, len(review_rows), 1_000):
        session.execute(
            insert(Review)
            .values(review_rows[start : start + 1_000])
            .on_conflict_do_nothing(index_elements=[Review.source_record_key])
        )
    session.commit()
    reviews_after = int(
        session.scalar(
            select(func.count(Review.id)).where(Review.product_id.in_(selected_product_ids))
        )
        or 0
    )
    return {
        "products_upserted": len(selected),
        "reviews_inserted": reviews_after - reviews_before,
        "reviews_present": reviews_after,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="선정한 카테고리 상품 2개의 연속 3개월 리뷰를 PostgreSQL에 적재합니다."
    )
    parser.add_argument("--category", choices=sorted(CATEGORY_SOURCES), required=True)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    selected = load_selection(args.selection, args.category)
    metadata = read_metadata(args.category, args.input, set(selected))
    review_rows, audit, monthly = selected_review_rows(
        args.category, args.input, selected
    )
    validate_selected_counts(selected, monthly)
    with SessionLocal() as session:
        database = upsert_data(
            session, args.category, selected, metadata, review_rows
        )

    source = CATEGORY_SOURCES[args.category]
    report = {
        "source": SOURCE_NAME,
        "source_category": args.category,
        "category_name_ko": source.korean_name,
        "review_revision": source.reviews.revision,
        "metadata_revision": source.metadata.revision,
        "products": [
            {
                "parent_asin": parent_asin,
                "title": metadata[parent_asin]["title"],
                "months": selected[parent_asin]["months"],
                "monthly_counts": monthly[parent_asin],
                "review_count": sum(monthly[parent_asin].values()),
            }
            for parent_asin in selected
        ],
        "audit": audit,
        "database": database,
    }
    args.report.mkdir(parents=True, exist_ok=True)
    report_path = args.report / f"{args.category.lower()}_import_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"적재 보고서 저장: {report_path}")


if __name__ == "__main__":
    main()
