from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

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
from scripts.amazon_reviews_source import (
    METADATA_FILE,
    METADATA_REVISION,
    REVIEW_FILES,
    REVIEW_REVISION,
)

DEFAULT_INPUT = Path("data/raw/amazon_reviews_2023")
DEFAULT_SELECTION = Path("config/amazon_appliances_selection.json")
DEFAULT_REPORT = Path("data/processed/appliances_import_report.json")
REVIEW_COLUMNS = [
    "rating",
    "title",
    "text",
    "asin",
    "parent_asin",
    "user_id",
    "timestamp",
]


def _month(value: int) -> str:
    return timestamp_ms_to_utc(value).strftime("%Y-%m")


def _first_image(images: Any) -> str | None:
    if not isinstance(images, dict):
        return None
    for size in ("hi_res", "large", "thumb"):
        values = images.get(size) or []
        for value in values:
            if value:
                return str(value)
    return None


def _description(value: Any) -> str | None:
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(cleaned) or None
    cleaned = str(value or "").strip()
    return cleaned or None


def load_selection(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    products = payload.get("products", [])
    if len(products) != 3:
        raise ValueError("selection must contain exactly three products")
    selected = {item["parent_asin"]: item for item in products}
    if len(selected) != 3:
        raise ValueError("selection parent_asin values must be unique")
    return selected


def read_metadata(input_root: Path, selected_ids: set[str]) -> dict[str, dict[str, Any]]:
    path = input_root / METADATA_FILE.path
    columns = [
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
    result: dict[str, dict[str, Any]] = {}
    for batch in pq.ParquetFile(path).iter_batches(batch_size=32_768, columns=columns):
        values = batch.to_pydict()
        for index in range(batch.num_rows):
            parent_asin = values["parent_asin"][index]
            if parent_asin in selected_ids:
                result[parent_asin] = {
                    name: column[index] for name, column in values.items()
                }
    missing = selected_ids - result.keys()
    if missing:
        raise ValueError(f"metadata missing for selected parent_asin values: {sorted(missing)}")
    return result


def selected_review_rows(
    input_root: Path, selected: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: dict[str, dict[str, Any]] = {}
    audit = Counter()
    for remote_file in REVIEW_FILES:
        path = input_root / remote_file.path
        for batch in pq.ParquetFile(path).iter_batches(
            batch_size=65_536, columns=REVIEW_COLUMNS
        ):
            values = batch.to_pydict()
            for index in range(batch.num_rows):
                parent_asin = values["parent_asin"][index]
                selection = selected.get(parent_asin)
                if selection is None:
                    continue
                record = {name: column[index] for name, column in values.items()}
                audit["selected_source_rows"] += 1
                if not is_eligible_review(record):
                    audit["excluded_ineligible"] += 1
                    continue
                month = _month(record["timestamp"])
                if not (
                    selection["import_start_month"]
                    <= month
                    <= selection["import_end_month"]
                ):
                    audit["excluded_outside_period"] += 1
                    continue
                identity = review_identity(record)
                key = source_record_key(identity)
                if key in rows:
                    audit["excluded_duplicate"] += 1
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
    audit["eligible_unique_import_rows"] = len(rows)
    return list(rows.values()), dict(audit)


def upsert_data(
    session: Session,
    selected: dict[str, dict[str, Any]],
    metadata: dict[str, dict[str, Any]],
    review_rows: list[dict[str, Any]],
) -> dict[str, int]:
    selected_product_ids = [product_id(value) for value in selected]
    reviews_before = int(
        session.scalar(
            select(func.count(Review.id)).where(
                Review.product_id.in_(selected_product_ids)
            )
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
            "category": "Appliances",
            "image_url": _first_image(item.get("images")),
            "metadata_json": {
                "fixture": False,
                "source_category": "Appliances",
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
                "review_revision": REVIEW_REVISION,
                "metadata_revision": METADATA_REVISION,
                "baseline_month": selection["baseline_month"],
                "target_month": selection["target_month"],
                "import_start_month": selection["import_start_month"],
                "import_end_month": selection["import_end_month"],
            },
        }
        statement = insert(Product).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[Product.id],
            set_={key: value for key, value in values.items() if key != "id"},
        )
        session.execute(statement)

    for start in range(0, len(review_rows), 1_000):
        batch = review_rows[start : start + 1_000]
        statement = insert(Review).values(batch).on_conflict_do_nothing(
            index_elements=[Review.source_record_key]
        )
        session.execute(statement)
    session.commit()
    reviews_after = int(
        session.scalar(
            select(func.count(Review.id)).where(
                Review.product_id.in_(selected_product_ids)
            )
        )
        or 0
    )
    return {
        "products_upserted": len(selected),
        "reviews_inserted": reviews_after - reviews_before,
        "reviews_present": reviews_after,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the three selected real products.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    selected = load_selection(args.selection)
    metadata = read_metadata(args.input, set(selected))
    review_rows, audit = selected_review_rows(args.input, selected)
    with SessionLocal() as session:
        database = upsert_data(session, selected, metadata, review_rows)

    report = {
        "source": SOURCE_NAME,
        "source_category": "Appliances",
        "review_revision": REVIEW_REVISION,
        "metadata_revision": METADATA_REVISION,
        "products": [
            {
                "parent_asin": parent_asin,
                "title": metadata[parent_asin]["title"],
                "monthly_counts": selected[parent_asin]["monthly_counts"],
            }
            for parent_asin in selected
        ],
        "audit": audit,
        "database": database,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
