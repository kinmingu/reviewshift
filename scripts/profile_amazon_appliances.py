from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from backend.app.importers.amazon_reviews import is_eligible_review
from scripts.amazon_reviews_source import METADATA_FILE, REVIEW_FILES

DEFAULT_INPUT = Path("data/raw/amazon_reviews_2023")
DEFAULT_OUTPUT = Path("data/processed/appliances_profile.json")
REVIEW_COLUMNS = [
    "rating",
    "title",
    "text",
    "asin",
    "parent_asin",
    "user_id",
    "timestamp",
]


def month_from_timestamp(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m")


def previous_month(value: str) -> str:
    year, month = (int(part) for part in value.split("-"))
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


def shift_month(value: str, delta: int) -> str:
    year, month = (int(part) for part in value.split("-"))
    index = year * 12 + month - 1 + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def compact_identity(record: dict[str, Any]) -> bytes:
    payload = json.dumps(
        {
            "user_id": record.get("user_id"),
            "asin": record.get("asin"),
            "parent_asin": record.get("parent_asin"),
            "timestamp": record.get("timestamp"),
            "rating": record.get("rating"),
            "title": record.get("title"),
            "text": record.get("text"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.blake2b(payload, digest_size=16).digest()


def profile_reviews(input_root: Path) -> tuple[dict[str, Counter[str]], dict[str, Any]]:
    monthly: dict[str, Counter[str]] = defaultdict(Counter)
    seen: set[bytes] = set()
    audit = Counter()
    observed_months: set[str] = set()

    for remote_file in REVIEW_FILES:
        path = input_root / remote_file.path
        if not path.exists():
            raise FileNotFoundError(path)
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=65_536, columns=REVIEW_COLUMNS):
            columns = batch.to_pydict()
            for index in range(batch.num_rows):
                record = {name: values[index] for name, values in columns.items()}
                audit["total_rows"] += 1
                if not str(record.get("text") or "").strip():
                    audit["missing_text"] += 1
                if not str(record.get("parent_asin") or "").strip():
                    audit["missing_parent_asin"] += 1
                identity = compact_identity(record)
                if identity in seen:
                    audit["exact_duplicate_rows"] += 1
                else:
                    seen.add(identity)
                if not is_eligible_review(record):
                    audit["excluded_rows"] += 1
                    continue
                month = month_from_timestamp(record["timestamp"])
                observed_months.add(month)
                monthly[record["parent_asin"]][month] += 1
                audit["eligible_rows"] += 1

    audit["unique_identity_rows"] = len(seen)
    return monthly, {
        **audit,
        "first_observed_month": min(observed_months),
        "last_observed_month": max(observed_months),
    }


def candidate_rows(monthly: dict[str, Counter[str]], last_month: str) -> list[dict[str, Any]]:
    last_complete_month = previous_month(last_month)
    candidates = []
    for parent_asin, counts in monthly.items():
        pairs = []
        for target_month, target_count in counts.items():
            if target_month > last_complete_month:
                continue
            baseline_month = previous_month(target_month)
            baseline_count = counts.get(baseline_month, 0)
            if target_count >= 30 and baseline_count >= 30:
                pairs.append(
                    (
                        min(target_count, baseline_count),
                        target_month,
                        baseline_month,
                        target_count,
                        baseline_count,
                    )
                )
        if not pairs:
            continue
        minimum, target, baseline, target_count, baseline_count = max(pairs)
        import_start = shift_month(target, -11)
        twelve_month_counts = {
            month: count
            for month, count in sorted(counts.items())
            if import_start <= month <= target
        }
        candidates.append(
            {
                "parent_asin": parent_asin,
                "baseline_month": baseline,
                "target_month": target,
                "baseline_count": baseline_count,
                "target_count": target_count,
                "minimum_pair_count": minimum,
                "import_start_month": import_start,
                "import_end_month": target,
                "monthly_counts": twelve_month_counts,
                "import_review_count": sum(twelve_month_counts.values()),
            }
        )
    candidates.sort(
        key=lambda item: (
            -item["minimum_pair_count"],
            -item["import_review_count"],
            item["parent_asin"],
        )
    )
    return candidates


def metadata_for_candidates(
    input_root: Path, candidate_ids: set[str]
) -> dict[str, dict[str, Any]]:
    path = input_root / METADATA_FILE.path
    if not path.exists():
        raise FileNotFoundError(path)
    columns = [
        "parent_asin",
        "title",
        "main_category",
        "average_rating",
        "rating_number",
        "store",
        "images",
        "description",
    ]
    result = {}
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=32_768, columns=columns):
        values = batch.to_pydict()
        for index in range(batch.num_rows):
            parent_asin = values["parent_asin"][index]
            if parent_asin not in candidate_ids:
                continue
            result[parent_asin] = {
                name: column[index] for name, column in values.items()
            }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Profile all local Appliances reviews and rank volume-based candidates."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top", type=int, default=50)
    args = parser.parse_args()

    monthly, audit = profile_reviews(args.input)
    candidates = candidate_rows(monthly, audit["last_observed_month"])
    metadata = metadata_for_candidates(
        args.input, {item["parent_asin"] for item in candidates}
    )
    enriched = []
    for candidate in candidates:
        item_metadata = metadata.get(candidate["parent_asin"])
        if not item_metadata or not str(item_metadata.get("title") or "").strip():
            continue
        enriched.append(
            {
                **candidate,
                "title": item_metadata["title"],
                "main_category": item_metadata["main_category"],
                "source_average_rating": item_metadata["average_rating"],
                "source_rating_number": item_metadata["rating_number"],
                "store": item_metadata["store"],
                "has_description": bool(item_metadata.get("description")),
                "has_image": bool(item_metadata.get("images")),
            }
        )
        if len(enriched) >= args.top:
            break

    profile = {
        "scope": "complete pinned Appliances review and metadata Parquet files",
        "audit": audit,
        "candidate_rule": (
            "rank by the largest minimum count across adjacent completed months; "
            "require at least 30 eligible reviews in both months; exclude the final observed month"
        ),
        "candidate_count_before_metadata_filter": len(candidates),
        "candidates": enriched,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(profile, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

