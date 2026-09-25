from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from scripts.amazon_category_sources import CATEGORY_SOURCES, list_remote_files

DEFAULT_INPUT = Path("data/raw/amazon_reviews_2023")
DEFAULT_OUTPUT = Path("data/processed")
REVIEW_COLUMNS = ["rating", "text", "asin", "parent_asin", "timestamp"]
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
MIN_TIMESTAMP_MS = int(datetime(1990, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
MAX_TIMESTAMP_MS = int(datetime(2101, 1, 1, tzinfo=timezone.utc).timestamp() * 1000) - 1


def shift_month(value: str, delta: int) -> str:
    """YYYY-MM 문자열을 달력 기준으로 이동합니다."""
    year, month = (int(part) for part in value.split("-"))
    index = year * 12 + month - 1 + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _non_empty(values: pa.Array) -> pa.Array:
    trimmed = pc.utf8_trim_whitespace(values)
    return pc.fill_null(pc.not_equal(trimmed, ""), False)


def _validity_masks(batch: pa.RecordBatch) -> dict[str, pa.Array]:
    rating = batch.column(batch.schema.get_field_index("rating"))
    timestamp = batch.column(batch.schema.get_field_index("timestamp"))
    rating_valid = pc.and_(
        pc.and_(pc.greater_equal(rating, 1), pc.less_equal(rating, 5)),
        pc.equal(rating, pc.floor(rating)),
    )
    timestamp_valid = pc.and_(
        pc.greater_equal(timestamp, MIN_TIMESTAMP_MS),
        pc.less_equal(timestamp, MAX_TIMESTAMP_MS),
    )
    masks = {
        "parent_asin": _non_empty(
            batch.column(batch.schema.get_field_index("parent_asin"))
        ),
        "asin": _non_empty(batch.column(batch.schema.get_field_index("asin"))),
        "text": _non_empty(batch.column(batch.schema.get_field_index("text"))),
        "rating": pc.fill_null(rating_valid, False),
        "timestamp": pc.fill_null(timestamp_valid, False),
    }
    eligible = masks["parent_asin"]
    for name in ("asin", "text", "rating", "timestamp"):
        eligible = pc.and_(eligible, masks[name])
    masks["eligible"] = eligible
    return masks


def _true_count(mask: pa.Array) -> int:
    return int(pc.sum(pc.cast(mask, pa.int64())).as_py() or 0)


def _review_paths(category: str, input_root: Path) -> list[Path]:
    source = CATEGORY_SOURCES[category]
    paths = [input_root / item.path for item in list_remote_files(source, "reviews")]
    missing = [path for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"리뷰 Parquet {len(missing)}개가 없습니다. 예: {missing[0]}")
    return paths


def count_products(
    paths: list[Path], batch_size: int
) -> tuple[Counter[str], dict[str, int | str]]:
    """첫 번째 통과에서는 상품별 총량만 세어 메모리 사용을 제한합니다."""
    product_counts: Counter[str] = Counter()
    audit: Counter[str] = Counter()
    first_timestamp: int | None = None
    last_timestamp: int | None = None

    for file_index, path in enumerate(paths, start=1):
        print(f"[1/2] 리뷰 총량 집계 {file_index}/{len(paths)}: {path.name}", flush=True)
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=batch_size, columns=REVIEW_COLUMNS):
            masks = _validity_masks(batch)
            audit["total_rows"] += batch.num_rows
            for field in ("parent_asin", "asin", "text", "rating", "timestamp"):
                audit[f"invalid_{field}"] += batch.num_rows - _true_count(masks[field])
            eligible_count = _true_count(masks["eligible"])
            audit["eligible_rows"] += eligible_count
            if not eligible_count:
                continue

            table = pa.Table.from_batches([batch]).filter(masks["eligible"])
            grouped = table.select(["parent_asin", "timestamp"]).group_by(
                "parent_asin"
            ).aggregate([("timestamp", "count")])
            for parent_asin, count in zip(
                grouped["parent_asin"].to_pylist(),
                grouped["timestamp_count"].to_pylist(),
                strict=True,
            ):
                product_counts[parent_asin] += int(count)

            timestamp = table["timestamp"]
            batch_min = int(pc.min(timestamp).as_py())
            batch_max = int(pc.max(timestamp).as_py())
            first_timestamp = batch_min if first_timestamp is None else min(first_timestamp, batch_min)
            last_timestamp = batch_max if last_timestamp is None else max(last_timestamp, batch_max)

    if first_timestamp is None or last_timestamp is None:
        raise ValueError("분석 가능한 리뷰가 없습니다.")
    audit_result: dict[str, int | str] = dict(audit)
    audit_result.update(
        {
            "eligible_product_count": len(product_counts),
            "first_observed_month": datetime.fromtimestamp(
                first_timestamp / 1000, tz=timezone.utc
            ).strftime("%Y-%m"),
            "last_observed_month": datetime.fromtimestamp(
                last_timestamp / 1000, tz=timezone.utc
            ).strftime("%Y-%m"),
        }
    )
    return product_counts, audit_result


def count_candidate_months(
    paths: list[Path], candidate_ids: set[str], batch_size: int
) -> dict[str, Counter[str]]:
    """두 번째 통과에서는 3개월 최소치가 가능한 상품의 월별 건수만 셉니다."""
    monthly: dict[str, Counter[str]] = defaultdict(Counter)
    candidate_values = pa.array(sorted(candidate_ids), type=pa.string())
    for file_index, path in enumerate(paths, start=1):
        print(f"[2/2] 후보 월별 집계 {file_index}/{len(paths)}: {path.name}", flush=True)
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=batch_size, columns=REVIEW_COLUMNS):
            masks = _validity_masks(batch)
            parent = batch.column(batch.schema.get_field_index("parent_asin"))
            selected = pc.and_(
                masks["eligible"], pc.fill_null(pc.is_in(parent, candidate_values), False)
            )
            if not _true_count(selected):
                continue
            table = pa.Table.from_batches([batch]).filter(selected)
            month = pc.strftime(
                pc.cast(table["timestamp"], pa.timestamp("ms", tz="UTC")),
                format="%Y-%m",
            )
            table = table.append_column("month", month)
            grouped = table.select(["parent_asin", "timestamp", "month"]).group_by(
                ["parent_asin", "month"]
            ).aggregate([("timestamp", "count")])
            for parent_asin, value_month, count in zip(
                grouped["parent_asin"].to_pylist(),
                grouped["month"].to_pylist(),
                grouped["timestamp_count"].to_pylist(),
                strict=True,
            ):
                monthly[parent_asin][value_month] += int(count)
    return monthly


def rank_windows(
    monthly: dict[str, Counter[str]], last_observed_month: str
) -> list[dict[str, Any]]:
    """감성 방향은 보지 않고 리뷰 양과 월별 균형만으로 3개월 구간을 고릅니다."""
    last_complete_month = shift_month(last_observed_month, -1)
    results: list[dict[str, Any]] = []
    for parent_asin, counts in monthly.items():
        windows = []
        for end_month in sorted(counts):
            if end_month > last_complete_month:
                continue
            months = [shift_month(end_month, -2), shift_month(end_month, -1), end_month]
            values = [counts.get(month, 0) for month in months]
            total = sum(values)
            if min(values) < 30 or not 150 <= total <= 600:
                continue
            windows.append(
                {
                    "months": months,
                    "monthly_counts": dict(zip(months, values, strict=True)),
                    "review_count": total,
                    "balance_gap": max(values) - min(values),
                }
            )
        if not windows:
            continue
        # 375건은 요청 범위(150~600)의 중앙값입니다. 중앙에 가깝고 월 편차가 작은 구간을 우선합니다.
        best = min(
            windows,
            key=lambda item: (
                abs(item["review_count"] - 375),
                item["balance_gap"],
                -int(item["months"][-1].replace("-", "")),
            ),
        )
        results.append({"parent_asin": parent_asin, **best})
    results.sort(
        key=lambda item: (
            abs(item["review_count"] - 375),
            item["balance_gap"],
            item["parent_asin"],
        )
    )
    return results


def read_candidate_metadata(
    category: str,
    input_root: Path,
    candidate_ids: set[str],
    batch_size: int,
) -> dict[str, dict[str, Any]]:
    source = CATEGORY_SOURCES[category]
    remote_files = list_remote_files(source, "metadata")
    paths = [input_root / item.path for item in remote_files]
    missing = [path for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"메타데이터 Parquet {len(missing)}개가 없습니다. 예: {missing[0]}")

    result: dict[str, dict[str, Any]] = {}
    candidate_values = pa.array(sorted(candidate_ids), type=pa.string())
    for file_index, path in enumerate(paths, start=1):
        print(f"후보 메타데이터 조회 {file_index}/{len(paths)}: {path.name}", flush=True)
        for batch in pq.ParquetFile(path).iter_batches(
            batch_size=batch_size, columns=METADATA_COLUMNS
        ):
            parent = batch.column(batch.schema.get_field_index("parent_asin"))
            selected = pc.fill_null(pc.is_in(parent, candidate_values), False)
            if not _true_count(selected):
                continue
            for row in pa.Table.from_batches([batch]).filter(selected).to_pylist():
                parent_asin = row["parent_asin"]
                if str(row.get("title") or "").strip():
                    result[parent_asin] = row
    return result


def _compact_metadata(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": value.get("title"),
        "main_category": value.get("main_category"),
        "store": value.get("store"),
        "source_average_rating": value.get("average_rating"),
        "source_rating_number": value.get("rating_number"),
        "has_image": bool(value.get("images")),
        "has_description": bool(value.get("description")),
        "feature_preview": (value.get("features") or [])[:3],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="공식 Amazon Reviews 2023 카테고리를 상품·월 단위로 프로파일링합니다."
    )
    parser.add_argument("--category", choices=sorted(CATEGORY_SOURCES), required=True)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top", type=int, default=100)
    parser.add_argument("--metadata-candidates", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=131_072)
    args = parser.parse_args()

    paths = _review_paths(args.category, args.input)
    product_counts, audit = count_products(paths, args.batch_size)
    # 3개월마다 30건이 필요하므로 전체 90건 미만 상품은 두 번째 통과 전에 안전하게 제외합니다.
    possible_ids = {key for key, count in product_counts.items() if count >= 90}
    monthly = count_candidate_months(paths, possible_ids, args.batch_size)
    candidates = rank_windows(monthly, str(audit["last_observed_month"]))
    metadata_ids = {item["parent_asin"] for item in candidates[: args.metadata_candidates]}
    metadata = read_candidate_metadata(
        args.category, args.input, metadata_ids, args.batch_size
    )

    enriched = []
    for candidate in candidates:
        item_metadata = metadata.get(candidate["parent_asin"])
        if not item_metadata:
            continue
        enriched.append({**candidate, **_compact_metadata(item_metadata)})
        if len(enriched) >= args.top:
            break

    source = CATEGORY_SOURCES[args.category]
    profile = {
        "source": "McAuley-Lab/Amazon-Reviews-2023",
        "category": args.category,
        "korean_category": source.korean_name,
        "review_revision": source.reviews.revision,
        "metadata_revision": source.metadata.revision,
        "scope": "complete pinned category review and metadata Parquet files",
        "audit": audit,
        "products_with_at_least_90_eligible_reviews": len(possible_ids),
        "products_matching_three_month_rule": len(candidates),
        "candidate_rule": (
            "three consecutive completed months, at least 30 eligible reviews per month, "
            "150-600 reviews total; ranked by volume near 375 and monthly balance only"
        ),
        "candidates": enriched,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    output_path = args.output / f"{args.category.lower()}_profile.json"
    output_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Windows 기본 콘솔(cp949)이 일부 원문 상품명 문자를 출력하지 못해도 결과 저장은 실패하지 않게 합니다.
    print(json.dumps({**profile, "candidates": enriched[:10]}, ensure_ascii=True, indent=2))
    print(f"전체 후보 보고서 저장: {output_path}")


if __name__ == "__main__":
    main()
