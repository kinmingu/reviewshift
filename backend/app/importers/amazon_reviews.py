from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

SOURCE_NAME = "McAuley-Lab/Amazon-Reviews-2023"


def timestamp_ms_to_utc(value: int) -> datetime:
    if not isinstance(value, int):
        raise ValueError("timestamp must be an integer")
    result = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    if result.year < 1990 or result.year > 2100:
        raise ValueError("timestamp is outside the supported range")
    return result


def normalized_rating(value: float | int) -> int:
    rating = int(value)
    if float(value) != rating or rating < 1 or rating > 5:
        raise ValueError("rating must be an integer from 1 through 5")
    return rating


def review_identity(record: dict[str, Any]) -> str:
    identity = {
        "user_id": record.get("user_id"),
        "asin": record.get("asin"),
        "parent_asin": record.get("parent_asin"),
        "timestamp": record.get("timestamp"),
        "rating": record.get("rating"),
        "title": record.get("title"),
        "text": record.get("text"),
    }
    payload = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def product_id(parent_asin: str) -> str:
    return f"amazon-{parent_asin}"


def review_id(identity: str) -> str:
    return f"amazon-{identity[:40]}"


def source_record_key(identity: str) -> str:
    return f"amazon-reviews-2023:{identity}"


def is_eligible_review(record: dict[str, Any]) -> bool:
    if not str(record.get("parent_asin") or "").strip():
        return False
    if not str(record.get("asin") or "").strip():
        return False
    if not str(record.get("text") or "").strip():
        return False
    try:
        timestamp_ms_to_utc(record["timestamp"])
        normalized_rating(record["rating"])
    except (KeyError, TypeError, ValueError, OSError, OverflowError):
        return False
    return True

