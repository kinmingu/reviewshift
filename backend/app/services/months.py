import re
from datetime import datetime, timezone

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


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

