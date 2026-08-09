"""Deterministic temporal constraints for historical retrieval."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

_ISO_DATE = re.compile(r"(?<!\d)(?P<year>20\d{2})-(?P<month>\d{1,2})-(?P<day>\d{1,2})(?!\d)")
_DAY_FIRST = re.compile(
    r"(?<!\d)(?P<day>\d{1,2})[/-](?P<month>\d{1,2})[/-](?P<year>20\d{2})(?!\d)"
)
_VI_MONTH = re.compile(
    r"\bth[aá]ng\s+(?P<month>\d{1,2})(?:\s+n[aă]m\s+|[/-])(?P<year>20\d{2})\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class QueryTimeRange:
    """Closed calendar range explicitly requested by a user query."""

    start: date
    end: date
    precision: str

    def contains(self, value: date) -> bool:
        return self.start <= value <= self.end


def extract_query_time_range(query: str) -> QueryTimeRange | None:
    """Extract an explicit date/month without guessing from bare numbers."""
    for pattern, order in (
        (_ISO_DATE, ("year", "month", "day")),
        (_DAY_FIRST, ("year", "month", "day")),
    ):
        match = pattern.search(query)
        if match is None:
            continue
        values = {name: int(match.group(name)) for name in order}
        try:
            value = date(values["year"], values["month"], values["day"])
        except ValueError:
            return None
        return QueryTimeRange(value, value, "day")

    month_match = _VI_MONTH.search(query)
    if month_match is None:
        return None
    year = int(month_match.group("year"))
    month = int(month_match.group("month"))
    if not 1 <= month <= 12:
        return None
    last_day = calendar.monthrange(year, month)[1]
    return QueryTimeRange(
        date(year, month, 1),
        date(year, month, last_day),
        "month",
    )


__all__ = ["QueryTimeRange", "extract_query_time_range"]
