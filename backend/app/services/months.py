"""월(YYYY-MM) 문자열을 UTC 기간 [그달 1일, 다음 달 1일)로 바꾸는 도우미."""

import re
from datetime import datetime, timezone

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# '2022-03' → (2022-03-01 00:00 UTC, 2022-04-01 00:00 UTC). 형식이 틀리면 ValueError.
def month_bounds(value: str) -> tuple[datetime, datetime]:
    if not MONTH_PATTERN.fullmatch(value):
        raise ValueError("month must use YYYY-MM with a valid month")
    year, month = (int(part) for part in value.split("-"))
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end

