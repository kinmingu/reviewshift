from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from scripts.amazon_reviews_source import METADATA_FILE, REVIEW_FILES, HttpRangeReader

REVIEW_COLUMNS = [
    "rating",
    "title",
    "text",
    "asin",
    "parent_asin",
    "timestamp",
    "verified_purchase",
    "helpful_vote",
]
METADATA_COLUMNS = [
    "main_category",
    "title",
    "average_rating",
    "rating_number",
    "features",
    "description",
    "price",
    "images",
    "videos",
    "store",
    "categories",
    "details",
    "parent_asin",
]


def _timestamp_summary(values: list[int | None]) -> dict[str, Any]:
    present = [value for value in values if value is not None]
    if not present:
        return {"present": 0, "minimum": None, "maximum": None, "unit": "unknown"}
    magnitude = max(abs(value) for value in present)
    unit = "milliseconds" if magnitude >= 100_000_000_000 else "seconds"
    divisor = 1000 if unit == "milliseconds" else 1
    return {
        "present": len(present),
        "minimum": min(present),
        "maximum": max(present),
        "unit": unit,
        "minimum_utc": datetime.fromtimestamp(
            min(present) / divisor, tz=timezone.utc
        ).isoformat(),
        "maximum_utc": datetime.fromtimestamp(
            max(present) / divisor, tz=timezone.utc
        ).isoformat(),
    }


def inspect_file(remote_file, columns: list[str], sample_rows: int) -> dict[str, Any]:
    reader = HttpRangeReader(remote_file)
    try:
        parquet = pq.ParquetFile(reader)
        schema = parquet.schema_arrow
        available = [name for name in columns if name in schema.names]
        batch = next(
            parquet.iter_batches(
                batch_size=sample_rows,
                row_groups=[0],
                columns=available,
                use_threads=False,
            )
        )
        table = batch.to_pydict()
        result: dict[str, Any] = {
            "path": remote_file.path,
            "revision": remote_file.revision,
            "remote_size_bytes": remote_file.size,
            "row_count": parquet.metadata.num_rows,
            "row_groups": parquet.metadata.num_row_groups,
            "schema": {field.name: str(field.type) for field in schema},
            "sample_rows": batch.num_rows,
            "sample_missing": {
                name: sum(value is None or value == "" for value in values)
                for name, values in table.items()
            },
            "sample_parent_asins": list(
                dict.fromkeys(table.get("parent_asin", []))
            )[:10],
            "sample_asins": list(dict.fromkeys(table.get("asin", [])))[:10],
        }
        if "rating" in table:
            result["sample_ratings"] = sorted(
                {value for value in table["rating"] if value is not None}
            )
        if "timestamp" in table:
            result["timestamp"] = _timestamp_summary(table["timestamp"])
        if "title" in table:
            result["sample_titles"] = [
                value for value in table["title"] if value
            ][:5]
        return result
    finally:
        result_bytes = reader.bytes_transferred
        result_requests = reader.request_count
        reader.close()
        if "result" in locals():
            result["transferred_bytes"] = result_bytes
            result["range_requests"] = result_requests


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect a bounded sample of official Appliances Parquet files."
    )
    parser.add_argument("--rows", type=int, default=20)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/audit/appliances_sample_summary.json"),
    )
    args = parser.parse_args()
    if args.rows < 1 or args.rows > 1000:
        parser.error("--rows must be between 1 and 1000")

    summary = {
        "reviews": [
            inspect_file(remote_file, REVIEW_COLUMNS, args.rows)
            for remote_file in REVIEW_FILES
        ],
        "metadata": inspect_file(METADATA_FILE, METADATA_COLUMNS, args.rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

