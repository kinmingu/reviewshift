"""Amazon Reviews 2023 원본 레코드를 우리 DB 형식으로 바꾸는 규칙.

시각 변환, 별점 검사, 중복 제거용 고유 ID 계산, 분석 대상 리뷰 판정을 담당합니다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

SOURCE_NAME = "McAuley-Lab/Amazon-Reviews-2023"


# 밀리초 타임스탬프를 UTC 시각으로 바꿉니다(1990~2100년 밖이면 오류).
def timestamp_ms_to_utc(value: int) -> datetime:
    if not isinstance(value, int):
        raise ValueError("timestamp must be an integer")
    result = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    if result.year < 1990 or result.year > 2100:
        raise ValueError("timestamp is outside the supported range")
    return result


# 별점이 1~5 정수인지 확인하고 정수로 돌려줍니다.
def normalized_rating(value: float | int) -> int:
    rating = int(value)
    if float(value) != rating or rating < 1 or rating > 5:
        raise ValueError("rating must be an integer from 1 through 5")
    return rating


# 작성자·상품·시각·본문으로 리뷰 고유값(SHA-256)을 만듭니다. 완전히 같은 리뷰는 같은 값이 되어 중복이 제거됩니다.
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


# 아마존 상품 번호(ASIN)로 우리 상품 ID('amazon-ASIN')를 만듭니다.
def product_id(parent_asin: str) -> str:
    return f"amazon-{parent_asin}"


# 리뷰 고유값 앞부분으로 우리 리뷰 ID를 만듭니다.
def review_id(identity: str) -> str:
    return f"amazon-{identity[:40]}"


# 원본 데이터에서 어떤 레코드였는지 추적하는 키.
def source_record_key(identity: str) -> str:
    return f"amazon-reviews-2023:{identity}"


# 분석 대상 리뷰인지 판정합니다(상품 번호·본문·별점이 온전해야 함).
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

