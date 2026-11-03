"""Historical data retrieval and monthly aggregation.

Source of truth is ``public.call_session`` (the only historical call table in
the database). There is no monthly-aggregate table, so monthly totals and the
per-shift splits are derived here from the individual call rows.

All functions are read-only and safe to call against production data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from django.db.models import Count, Max, Min
from django.db.models.functions import TruncMonth

from apps.callers.models import CallSession
from .constants import SERIES_TO_SHIFT_ID, SHIFT_LABELS


# --------------------------------------------------------------------------- #
# Month helpers
# --------------------------------------------------------------------------- #
def month_start(value: date) -> date:
    """Return the first day of the month containing ``value``."""
    return value.replace(day=1)


def add_months(value: date, count: int) -> date:
    """Return the first day of the month ``count`` months after ``value``."""
    value = month_start(value)
    index = value.year * 12 + (value.month - 1) + count
    return date(index // 12, index % 12 + 1, 1)


def month_span(start: date, end: date) -> list[date]:
    """Every month start from ``start`` through ``end`` inclusive."""
    start, end = month_start(start), month_start(end)
    if end < start:
        return []
    months: list[date] = []
    cursor = start
    while cursor <= end:
        months.append(cursor)
        cursor = add_months(cursor, 1)
    return months


def parse_month(text: str) -> date:
    """Parse a ``"YYYY-MM"`` string into the first day of that month."""
    year, month = (int(part) for part in text.strip().split("-"))
    return date(year, month, 1)


# --------------------------------------------------------------------------- #
# Aggregation result
# --------------------------------------------------------------------------- #
@dataclass
class MonthlyAggregates:
    """Monthly call counts derived from ``call_session``.

    ``months`` covers the full inclusive span requested. ``observed`` holds the
    months that actually have at least one call. A month absent from
    ``observed`` is a *missing* observation and must not be treated as zero.
    """

    months: list[date] = field(default_factory=list)
    observed: dict[date, int] = field(default_factory=dict)
    total: dict[date, int] = field(default_factory=dict)
    morning: dict[date, int] = field(default_factory=dict)
    afternoon: dict[date, int] = field(default_factory=dict)
    night: dict[date, int] = field(default_factory=dict)
    unknown_shift: dict[date, int] = field(default_factory=dict)

    @property
    def present(self) -> list[date]:
        """Months with at least one recorded call, ascending."""
        return [m for m in self.months if m in self.observed]

    @property
    def missing(self) -> list[date]:
        """Months in the span with no observation at all."""
        return [m for m in self.months if m not in self.observed]

    @property
    def first_observed(self) -> Optional[date]:
        present = self.present
        return present[0] if present else None

    @property
    def last_observed(self) -> Optional[date]:
        present = self.present
        return present[-1] if present else None

    def series_values(self, name: str) -> dict[date, int]:
        """Return ``{month: count}`` for a series name (or 'total')."""
        if name == "total":
            return dict(self.total)
        return dict(getattr(self, name))


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #
def _normalise_month(value) -> date:
    if isinstance(value, datetime):
        return value.date().replace(day=1)
    return value.replace(day=1)


def latest_observed_month() -> Optional[date]:
    """First day of the most recent month that has any recorded call."""
    latest = (
        CallSession.objects.order_by("-session_call_date")
        .values_list("session_call_date", flat=True)
        .first()
    )
    return month_start(latest) if latest else None


def aggregate_monthly(start: Optional[date] = None, end: Optional[date] = None) -> MonthlyAggregates:
    """Aggregate ``call_session`` rows into monthly per-shift counts.

    When ``start``/``end`` are omitted the span is taken from the earliest to
    the latest call present in the database.
    """
    bounds = CallSession.objects.aggregate(
        first=Min("session_call_date"),
        last=Max("session_call_date"),
    )
    first_day = bounds["first"]
    last_day = bounds["last"]

    if start is None and first_day:
        start = month_start(first_day)
    if end is None and last_day:
        end = month_start(last_day)

    agg = MonthlyAggregates()
    if start is None or end is None:
        return agg

    start, end = month_start(start), month_start(end)
    agg.months = month_span(start, end)

    rows = (
        CallSession.objects.filter(
            session_call_date__gte=start,
            session_call_date__lt=add_months(end, 1),
        )
        .annotate(month=TruncMonth("session_call_date"))
        .values("month", "shift_id")
        .annotate(c=Count("session_id"))
    )

    by_month: dict[date, dict[int, int]] = {}
    for row in rows:
        month = _normalise_month(row["month"])
        by_month.setdefault(month, {})[row["shift_id"]] = row["c"]

    for month in agg.months:
        shifts = by_month.get(month)
        if not shifts:
            continue  # missing observation: deliberately not zero-filled
        total = sum(shifts.values())
        agg.observed[month] = total
        agg.total[month] = total
        agg.morning[month] = shifts.get(SERIES_TO_SHIFT_ID["morning"], 0)
        agg.afternoon[month] = shifts.get(SERIES_TO_SHIFT_ID["afternoon"], 0)
        agg.night[month] = shifts.get(SERIES_TO_SHIFT_ID["night"], 0)
        known = agg.morning[month] + agg.afternoon[month] + agg.night[month]
        unknown = total - known
        if unknown:
            agg.unknown_shift[month] = unknown

    return agg
