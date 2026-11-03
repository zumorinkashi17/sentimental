"""Validation and preprocessing for the forecasting pipeline.

Turns :class:`~apps.forecast.services.data.MonthlyAggregates` into validated,
per-series monthly DataFrames. Missing months are reported and excluded, never
converted to zero. Incomplete months are never padded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd
from django.utils import timezone as django_timezone

from .constants import (
    ALL_SERIES,
    DEFAULT_TRAINING_START,
    SERIES_TO_SHIFT_ID,
)
from .data import (
    MonthlyAggregates,
    add_months,
    aggregate_monthly,
    latest_observed_month,
    month_start,
    month_span,
    parse_month,
)


@dataclass
class ValidationReport:
    """Outcome of validating one monthly aggregate set.

    ``issues`` blocks forecasting; ``warnings`` are documented but non-fatal.
    A month with no observation is a *warning* (it is excluded from the
    training data rather than being treated as zero), while a failed total
    reconciliation or an unmapped shift id is an ``issue``.
    """

    start: Optional[date] = None
    end: Optional[date] = None
    missing_months: list[date] = field(default_factory=list)
    unknown_shift_months: dict[date, int] = field(default_factory=dict)
    negative_months: list[date] = field(default_factory=list)
    reconciliation_failures: list[dict] = field(default_factory=list)
    zero_shift_months: dict[str, list[date]] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.issues and not self.reconciliation_failures and not self.negative_months

    def summary(self) -> str:
        lines = [
            f"Window: {self.start} .. {self.end}",
            f"Missing months: {len(self.missing_months)}",
            f"Unknown-shift months: {len(self.unknown_shift_months)}",
            f"Negative-count months: {len(self.negative_months)}",
            f"Reconciliation failures: {len(self.reconciliation_failures)}",
            f"Issues (blocking): {len(self.issues)}",
            f"Warnings: {len(self.warnings)}",
            f"Valid: {self.is_valid}",
        ]
        return "\n".join(lines)


def contiguous_frontier(present_months: list[date], start: date) -> Optional[date]:
    """Latest month reachable from ``start`` without a single missing month.

    Used to pick the training endpoint: trailing months after a gap (e.g. the
    empty 2026-05..07 stretch) are excluded rather than treated as zero.
    """
    present = set(present_months)
    cursor = month_start(start)
    frontier: Optional[date] = None
    while cursor in present:
        frontier = cursor
        index = cursor.year * 12 + (cursor.month - 1) + 1
        cursor = date(index // 12, index % 12 + 1, 1)
    return frontier


def resolve_window(
    start: Optional[date | str] = None,
    end: Optional[date | str] = None,
    exclude_current_month: bool = True,
) -> tuple[date, Optional[date]]:
    """Resolve the training window.

    ``start`` defaults to :data:`DEFAULT_TRAINING_START`. When ``end`` is
    omitted the endpoint is derived from the data as the latest contiguous
    month (see :func:`contiguous_frontier`), so trailing sparse/empty months
    are dropped automatically.

    When the endpoint is auto-derived and ``exclude_current_month`` is set, the
    calendar month currently in progress is never used as training data,
    because it is incomplete by definition. An explicitly supplied ``end`` is
    always respected.
    """
    if isinstance(start, str):
        start = parse_month(start)
    if isinstance(end, str):
        end = parse_month(end)
    start = month_start(start or parse_month(DEFAULT_TRAINING_START))

    if end is not None:
        return start, month_start(end)

    latest = latest_observed_month()
    if latest is None:
        return start, None
    if exclude_current_month:
        latest = min(latest, add_months(month_start(django_timezone.localdate()), -1))
    if latest < start:
        return start, None
    agg = aggregate_monthly(start=start, end=latest)
    return start, contiguous_frontier(agg.present, start)


def validate_aggregates(agg: MonthlyAggregates) -> ValidationReport:
    """Independently reconcile and sanity-check the monthly aggregates."""
    report = ValidationReport(
        start=agg.first_observed,
        end=agg.last_observed,
        missing_months=agg.missing,
        unknown_shift_months=dict(agg.unknown_shift),
    )

    for month in agg.present:
        morning = agg.morning[month]
        afternoon = agg.afternoon[month]
        night = agg.night[month]
        total = agg.total[month]
        known = morning + afternoon + night
        if known != total:
            report.reconciliation_failures.append(
                {
                    "month": month,
                    "morning": morning,
                    "afternoon": afternoon,
                    "night": night,
                    "known_sum": known,
                    "total": total,
                    "difference": total - known,
                }
            )
        for label, value in (
            ("total", total),
            ("morning", morning),
            ("afternoon", afternoon),
            ("night", night),
        ):
            if value < 0:
                report.negative_months.append(month)
                report.issues.append(f"Negative {label} count in {month:%Y-%m}")

    for name in ("morning", "afternoon", "night"):
        values = agg.series_values(name)
        zeros = [m for m in agg.present if values[m] == 0]
        if zeros:
            report.zero_shift_months[name] = zeros
            report.warnings.append(
                f"{len(zeros)} month(s) have zero {name} calls inside an observed month"
            )

    if report.missing_months:
        report.warnings.append(
            f"{len(report.missing_months)} month(s) have no observations "
            "(excluded from training, NOT treated as zero)"
        )
    if report.unknown_shift_months:
        report.issues.append(
            f"{len(report.unknown_shift_months)} month(s) contain calls with an unmapped shift_id"
        )
    return report


@dataclass
class SeriesData:
    """A validated monthly series ready for Prophet."""

    name: str
    frame: pd.DataFrame           # columns: ds (datetime), y (int)
    missing_months: list[date]
    zero_months: list[date]
    first: Optional[date]
    last: Optional[date]

    @property
    def observations(self) -> int:
        return len(self.frame)


def build_series(agg: MonthlyAggregates, name: str) -> SeriesData:
    """Build a single monthly series (``total`` or a shift) from aggregates."""
    if name not in ALL_SERIES:
        raise ValueError(f"unknown series {name!r}; expected one of {ALL_SERIES}")

    values = agg.series_values(name)
    # Only observed months are included. Shift value 0 inside an observed month
    # is a genuine zero (calls happened, none in that shift).
    records = [(month, values[month]) for month in agg.months if month in values]
    frame = pd.DataFrame(records, columns=["ds", "y"])
    if not frame.empty:
        frame["ds"] = pd.to_datetime(frame["ds"])
        frame["y"] = frame["y"].astype("int64")

    zero_months = [m for m, _ in records if values[m] == 0]
    return SeriesData(
        name=name,
        frame=frame,
        missing_months=agg.missing,
        zero_months=zero_months,
        first=records[0][0] if records else None,
        last=records[-1][0] if records else None,
    )


def build_all_series(agg: MonthlyAggregates) -> dict[str, SeriesData]:
    """Build all four validated series (total + three shifts)."""
    return {name: build_series(agg, name) for name in ALL_SERIES}
