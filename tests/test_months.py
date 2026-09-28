"""월 기간 변환 테스트: [그달 1일, 다음 달 1일) UTC 구간, 연도 넘김, 잘못된 형식 거부."""

from datetime import datetime, timezone

import pytest

from backend.app.services.months import month_bounds


def test_month_bounds_uses_half_open_utc_range() -> None:
    start, end = month_bounds("2025-02")
    assert start == datetime(2025, 2, 1, tzinfo=timezone.utc)
    assert end == datetime(2025, 3, 1, tzinfo=timezone.utc)


def test_month_bounds_crosses_year() -> None:
    start, end = month_bounds("2025-12")
    assert start == datetime(2025, 12, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("value", ["2025-00", "2025-13", "25-01", "2025/01"])
def test_month_bounds_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        month_bounds(value)

