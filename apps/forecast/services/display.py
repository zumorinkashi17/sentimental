"""Plain-language display helpers for the forecasting pages.

This module is the single place where *technical* forecast values are turned
into wording a helpline manager can read without any statistical background:

* **Time** - timestamps are stored in UTC and are shown in the application's
  local timezone (``Asia/Manila``, Philippine Time). The conversion is done
  with :meth:`datetime.astimezone`, i.e. the framework converts the value
  instead of the code adding eight hours by hand.
* **Shifts** - shift names and working hours are read from the ``shift_catalog``
  table, so the wording always matches the configured schedules. The internal
  ``shift_id`` values are never shown to users.
* **Periods** - "January 2020 - April 2026" style labels for the historical
  window and the forecast period.

Nothing here computes a forecast, changes a stored value or reads a forecast
table: it only formats values that other services have already produced.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

APP_TIMEZONE = ZoneInfo("Asia/Manila")
TIMEZONE_LABEL = "PHT"

# Working hours of the configured shifts, used to identify a catalog row and as
# a fallback when the catalog has no row for a shift id.
FALLBACK_SHIFT_HOURS = {
    1: (time(6, 0), time(14, 0)),
    3: (time(14, 0), time(22, 0)),
    4: (time(22, 0), time(6, 0)),
}

# Human names per shift id. The catalog table stores only the working hours,
# so the names live next to the verified id mapping in the forecast constants.
SHIFT_NAMES = {
    1: "Morning Shift",
    3: "Afternoon Shift",
    4: "Night Shift",
}

MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

MONTH_ABBR = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)




def format_time(value) -> str:
    """``14:00`` -> ``2:00 PM`` (portable: no ``%-I`` platform flag)."""
    if value is None:
        return ""
    if not hasattr(value, "strftime"):
        return str(value)
    return value.strftime("%I:%M %p").lstrip("0")


def format_hours(start, end, crosses_midnight: bool = False) -> str:
    """``6:00 AM–2:00 PM`` (with "next day" for shifts that cross midnight)."""
    label = f"{format_time(start)}–{format_time(end)}"
    if crosses_midnight:
        label += " (next day)"
    return label


def crosses_midnight(start, end) -> bool:
    """``True`` when a shift ends on the day after it starts."""
    if start is None or end is None:
        return False
    return end <= start


def month_name(month: date) -> str:
    """``date(2026, 4, 1)`` -> ``"April 2026"``."""
    return f"{MONTH_NAMES[month.month - 1]} {month.year}"


def month_range_label(start: Optional[date], end: Optional[date]) -> str:
    """``"January 2020 – April 2026"`` (or a single month when start == end)."""
    if not start or not end:
        return ""
    if start == end:
        return month_name(start)
    return f"{month_name(start)} – {month_name(end)}"


def format_timestamp(value) -> Optional[str]:
    """Format a stored timestamp for display in the application's timezone.

    Accepts a ``datetime`` (aware or naive) or an ISO string. A naive value is
    read as UTC, because that is how timestamps are stored; an aware value is
    converted to :data:`APP_TIMEZONE`. The result looks like
    ``"October 22, 2026, 4:20 AM PHT"``.
    """
    if value in (None, ""):
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        from datetime import timezone as _timezone

        value = value.replace(tzinfo=_timezone.utc)
    local = value.astimezone(APP_TIMEZONE)
    return (
        f"{local.strftime('%B')} {local.day}, {local.year}, "
        f"{local.strftime('%I:%M %p').lstrip('0')} {TIMEZONE_LABEL}"
    )


def _row_for_shift(rows: dict, shift_id: int, expected: tuple):
    """Find the catalog row that describes ``shift_id``.

    The forecast constants map a shift series to a ``shift_id`` and the
    configured catalog uses the same ids. A row is only accepted for an id when
    its working hours match the configured hours of that shift; otherwise the
    row with those working hours is used, so a catalog that numbers its rows
    differently still produces the correct wording.
    """
    expected_start, expected_end = expected
    by_id = rows.get(shift_id)
    if by_id is not None:
        if (by_id.shift_start_time, by_id.shift_end_time) == (expected_start, expected_end):
            return by_id
    for row in rows.values():
        if (row.shift_start_time, row.shift_end_time) == (expected_start, expected_end):
            return row
    return by_id


def shift_catalog_hours() -> dict[int, dict]:
    """Working hours per shift id, read from the configured shift catalog.

    Returns ``{shift_id: {"start": time, "end": time, "hours": "6:00 AM–2:00 PM"}}``.
    The catalog is the single source of truth for the schedules; the fallback
    hours are only used when no catalog row describes a shift.
    """
    from apps.schedules.models import ShiftCatalog

    rows = {row.shift_id: row for row in ShiftCatalog.objects.all().order_by("shift_id")}
    out: dict[int, dict] = {}
    for shift_id, expected in FALLBACK_SHIFT_HOURS.items():
        row = _row_for_shift(rows, shift_id, expected)
        if row is None:
            continue
        start = row.shift_start_time
        end = row.shift_end_time
        out[shift_id] = {
            "start": start,
            "end": end,
            "hours": format_hours(start, end, crosses_midnight(start, end)),
        }
    return out


def shift_display_map(series_to_shift_id: dict) -> dict[str, dict]:
    """Per-series display information: ``{series: {name, hours, label}}``.

    ``label`` is what a user reads, for example
    ``"Morning Shift (6:00 AM–2:00 PM)"``. The internal ``shift_id`` is kept
    out of every label.
    """
    catalog = shift_catalog_hours()
    out: dict[str, dict] = {}
    for series, shift_id in series_to_shift_id.items():
        name = SHIFT_NAMES.get(shift_id, "Shift")
        entry = catalog.get(shift_id)
        if entry:
            hours = entry["hours"]
        else:
            fallback = FALLBACK_SHIFT_HOURS.get(shift_id)
            if fallback:
                start, end = fallback
                hours = format_hours(start, end, crosses_midnight(start, end))
            else:
                hours = ""
        out[series] = {
            "name": name,
            "hours": hours,
            "label": f"{name} ({hours})" if hours else name,
        }
    return out


def enrich_busiest_shifts(items: list[dict], shift_labels: dict) -> list[dict]:
    """Add the friendly ``display_label`` to each busiest-shift entry.

    The machine-readable ``shift`` / ``label`` fields are left untouched so
    nothing that depends on them changes behaviour.
    """
    out = []
    for item in items:
        entry = dict(item)
        info = shift_labels.get(item.get("shift"))
        entry["display_label"] = info["label"] if info else item.get("label")
        entry["shift_name"] = info["name"] if info else item.get("label")
        entry["shift_hours"] = info["hours"] if info else ""
        out.append(entry)
    return out
