import calendar
import json
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count
from django.db.models.functions import ExtractMonth
from django.utils import timezone

from apps.accounts.models import User
from apps.callers.models import CallSession
from apps.referrals.models import Professional, SessionReferral

MANILA = ZoneInfo("Asia/Manila")

PERIODS = ("today", "week", "month", "range")
DEFAULT_PERIOD = "week"

CONTACT_ORDER = {"Email": 0, "Mobile": 1, "Landline": 2}

REASON_CATEGORIES = (
    ("Relationships", "#00a67e"),
    ("Suicidal Crisis", "#fbbf24"),
    ("Career", "#34d399"),
    ("Others", "#047857"),
)
GENDER_CATEGORIES = (
    ("Men", "#00a67e"),
    ("Women", "#34d399"),
    ("LGBTQIA", "#a7f3d0"),
)
REASON_MAP = {"relationship": "Relationships", "academic": "Career", "financial": "Career"}
SPEC_LABELS = {"Psychiatry": "Psychiatrists", "Psychology": "Psychologists"}
MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "June", "July", "Aug", "Sept", "Oct", "Nov", "Dec"]


def _today():
    return timezone.localdate(timezone=MANILA)


def period_bounds(period, start=None, end=None):
    """Inclusive (start, end) dates for a period, computed in Asia/Manila.

    When period is "range" the supplied start/end are used; if they are
    missing (first visit to Custom Range) the current week becomes the
    default window.
    """
    today = _today()
    if period == "range":
        if not (start and end):
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
        elif start > end:
            start, end = end, start
        return start, end
    if period == "today":
        return today, today
    if period == "month":
        return today.replace(day=1), today.replace(day=calendar.monthrange(today.year, today.month)[1])
    week_start = today - timedelta(days=today.weekday())
    return week_start, week_start + timedelta(days=6)


def _parse_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def available_years():
    years = sorted({d.year for d in CallSession.objects.values_list("session_call_date", flat=True)}, reverse=True)
    current = _today().year
    if current not in years:
        years.insert(0, current)
    return years


def _resolve_year(raw, years):
    try:
        year = int(raw)
    except (TypeError, ValueError):
        year = None
    if year in years:
        return year
    current = _today().year
    return current if current in years else years[0]


def percentages(counts):
    """Whole-number percentages that always sum to 100 (0 when empty)."""
    total = sum(counts)
    if not total:
        return [0 for _ in counts]
    pcts = [round(count * 100 / total) for count in counts]
    drift = 100 - sum(pcts)
    if drift:
        pcts[counts.index(max(counts))] += drift
    return pcts


def reason_category(value):
    if not value:
        return "Others"
    reason = value.strip().lower()
    if "suicid" in reason:
        return "Suicidal Crisis"
    return REASON_MAP.get(reason, "Others")


def gender_bucket(value):
    if not value:
        return None
    gender = value.strip().lower()
    if gender in ("male", "m"):
        return "Men"
    if gender in ("female", "f"):
        return "Women"
    if any(token in gender for token in ("lgbt", "queer", "trans", "non-binary", "nonbinary", "other")):
        return "LGBTQIA"
    return None


def _breakdown(queryset, field, categories, bucket_fn):
    counts = Counter(filter(None, (bucket_fn(value) for value in queryset.values_list(field, flat=True))))
    pcts = percentages([counts.get(label, 0) for label, _ in categories])
    return [
        {"label": label, "color": color, "count": counts.get(label, 0), "pct": pct}
        for (label, color), pct in zip(categories, pcts)
    ]


def _gauge(year):
    sessions = CallSession.objects.filter(session_call_date__year=year)
    total = sessions.count()
    high = sessions.filter(session_risk_assessment__icontains="high").count()
    pct = round(high * 100 / total) if total else 0
    return {"pct": pct, "high": high, "total": total, "chart": json.dumps([pct, 100 - pct])}


def _month_delta(counts):
    last = None
    for index, count in enumerate(counts):
        if count:
            last = index
    if last is None or last == 0 or not counts[last - 1]:
        return {"label": "—", "dir": "flat"}
    pct = (counts[last] - counts[last - 1]) * 100 / counts[last - 1]
    return {"label": f"{round(abs(pct))}%", "dir": "up" if pct >= 0 else "down"}


def _volume(year):
    rows = (
        CallSession.objects.filter(session_call_date__year=year)
        .values(month=ExtractMonth("session_call_date"))
        .annotate(total=Count("session_id"))
    )
    counts = [0 for _ in MONTH_LABELS]
    for row in rows:
        counts[int(row["month"]) - 1] = row["total"]
    return {"counts": counts, "total": sum(counts), "chart": json.dumps(counts), "delta": _month_delta(counts)}


def _referrals():
    rows = (
        Professional.objects.filter(professional_status=Professional.StatusChoices.ACTIVE)
        .values("professional_specialization")
        .annotate(count=Count("professional_id"))
    )
    items = [
        {
            "label": SPEC_LABELS.get(row["professional_specialization"], f"{row['professional_specialization']}s"),
            "count": row["count"],
        }
        for row in rows
    ]
    items.sort(key=lambda item: (-item["count"], item["label"]))
    ceiling = max([item["count"] for item in items], default=0) or 1
    for item in items:
        item["pct"] = round(item["count"] * 100 / ceiling)
    return items


def _contacts(limit=6):
    professionals = (
        Professional.objects.filter(professional_status=Professional.StatusChoices.ACTIVE)
        .select_related("institution")
        .prefetch_related("professionalcontact_set")
        .order_by("professional_name")[:limit]
    )
    rows = []
    for professional in professionals:
        contacts = sorted(
            professional.professionalcontact_set.all(),
            key=lambda contact: (CONTACT_ORDER.get(contact.contact_type, 9), contact.contact_type),
        )
        institution = professional.institution
        rows.append(
            {
                "name": professional.professional_name,
                "gender": professional.professional_gender or "—",
                "location": (institution.institution_location or "").strip() or institution.institution_name,
                "contacts": [{"type": contact.contact_type, "value": contact.contact_number} for contact in contacts],
                "institution": institution.institution_name,
            }
        )
    return rows


def responder_context(request, user):
    """Everything the responder dashboard needs, ready for the template."""
    period = request.GET.get("period", DEFAULT_PERIOD)
    if period not in PERIODS:
        period = DEFAULT_PERIOD

    range_start = _parse_date(request.GET.get("start"))
    range_end = _parse_date(request.GET.get("end"))

    years = available_years()
    year = _resolve_year(request.GET.get("year"), years)

    start, end = period_bounds(period, range_start, range_end)
    in_period = CallSession.objects.filter(session_call_date__gte=start, session_call_date__lte=end)

    reasons = _breakdown(in_period, "session_reason_for_calling", REASON_CATEGORIES, reason_category)
    callers = _breakdown(in_period, "caller__caller_gender", GENDER_CATEGORIES, gender_bucket)

    range_label = f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}" if period == "range" else ""

    return {
        "greeting_name": (user.user_first_name if user else "") or "Responder",
        "period": period,
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "range_label": range_label,
        "years": years,
        "year": year,
        "reasons": reasons,
        "reasons_total": sum(item["count"] for item in reasons),
        "reasons_chart": json.dumps([item["count"] for item in reasons]),
        "callers": callers,
        "callers_total": sum(item["count"] for item in callers),
        "callers_chart": json.dumps([item["count"] for item in callers]),
        "gauge": _gauge(year),
        "volume": _volume(year),
        "referrals": _referrals(),
        "contacts": _contacts(),
    }


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------

ADMIN_PERIODS = ("today", "week", "month", "range")
DEFAULT_ADMIN_PERIOD = "week"
ADMIN_PERIOD_OPTIONS = (
    ("today", "Today"),
    ("week", "This Week"),
    ("month", "This Month"),
    ("range", "Custom Range"),
)
ADMIN_ALERTS_LIMIT = 5


def admin_period_bounds(period, start=None, end=None):
    today = _today()
    if period == "range":
        if not (start and end):
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
        elif start > end:
            start, end = end, start
        return start, end
    if period == "today":
        return today, today
    if period == "month":
        return today.replace(day=1), today.replace(day=calendar.monthrange(today.year, today.month)[1])
    return today - timedelta(days=today.weekday()), today - timedelta(days=today.weekday()) + timedelta(days=6)


def _previous_window(period, start, end):
    span = (end - start).days + 1
    return start - timedelta(days=span), start - timedelta(days=1)


def _trend(current, previous):
    if not previous:
        return {"label": "", "dir": "", "color": "text-gray-400", "note": "No previous period data"}
    delta = round((current - previous) * 100 / previous)
    if delta == 0:
        return {"label": "0% vs last period", "dir": "flat", "color": "text-gray-400", "note": None}
    rising = delta > 0
    return {
        "label": f"{'+' if rising else ''}{delta}% vs last period",
        "dir": "up" if rising else "down",
        "color": "text-brand" if rising else "text-red-500",
        "note": None,
    }


def _avg_duration(sessions):
    total_seconds = 0
    count = 0
    for called, ended in sessions.values_list("session_time_called", "session_time_ended"):
        if not called or not ended:
            continue
        seconds = (datetime.combine(date.min, ended) - datetime.combine(date.min, called)).total_seconds()
        if seconds < 0:
            seconds += 24 * 3600
        total_seconds += seconds
        count += 1
    return count, round(total_seconds / count) if count else 0


def _risk_badge(value):
    risk = (value or "").lower()
    if "high" in risk:
        return "bg-red-100 text-red-700"
    if "med" in risk or "mod" in risk:
        return "bg-orange-100 text-orange-700"
    return "bg-gray-100 text-gray-600"


def _time_ago(day, clock):
    moment = datetime.combine(day, clock)
    now = timezone.localtime(timezone.now(), MANILA).replace(tzinfo=None)
    diff = (now - moment).total_seconds()
    if diff < 60:
        return "Just now"
    if diff < 3600:
        return f"{int(diff // 60)}m ago"
    if diff < 86400:
        return f"{int(diff // 3600)}h ago"
    if diff < 7 * 86400:
        return f"{int(diff // 86400)}d ago"
    return moment.strftime("%b %d, %Y")


def _alerts(sessions, limit=ADMIN_ALERTS_LIMIT):
    sessions = sessions.filter(session_risk_assessment__icontains="high")
    rows = list(sessions.select_related("caller", "user").order_by("-session_call_date", "-session_time_called")[:limit])
    alerts = []
    for session in rows:
        responder = session.user
        alerts.append(
            {
                "id": session.session_id,
                "risk": session.session_risk_assessment or "",
                "badge": _risk_badge(session.session_risk_assessment),
                "location": (session.caller.caller_location or "").strip() or "—",
                "handled_by": str(responder) if responder else "Unassigned",
                "time_ago": _time_ago(session.session_call_date, session.session_time_called),
            }
        )
    return alerts


def admin_context(request, user=None):
    """Everything the admin dashboard needs, ready for the template."""
    period = request.GET.get("period", DEFAULT_ADMIN_PERIOD)
    if period not in ADMIN_PERIODS:
        period = DEFAULT_ADMIN_PERIOD

    today = _today()
    range_start = _parse_date(request.GET.get("start"))
    range_end = _parse_date(request.GET.get("end"))
    start, end = admin_period_bounds(period, range_start, range_end)
    in_period = CallSession.objects.filter(session_call_date__gte=start, session_call_date__lte=end)
    range_label = f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}" if period == "range" else ""

    total = in_period.count()
    high = in_period.filter(session_risk_assessment__icontains="high").count()

    prev_start, prev_end = _previous_window(period, start, end)
    prev_total = CallSession.objects.filter(session_call_date__gte=prev_start, session_call_date__lte=prev_end).count()
    trend = _trend(total, prev_total)

    escalation = round(high * 100 / total) if total else 0

    duration_count, avg_seconds = _avg_duration(in_period)
    duration_label = "—" if not duration_count else f"{avg_seconds // 60} Mins"
    duration_pct = 0 if not duration_count else min(round(avg_seconds * 100 / 3600), 100)

    referrals = SessionReferral.objects.filter(
        session__session_call_date__gte=start, session__session_call_date__lte=end
    ).count()
    referral_rate = round(referrals * 100 / total) if total else 0

    active_responders = User.objects.filter(
        user_role=User.RoleChoices.RESPONDER, user_status=User.StatusChoices.ACTIVE
    ).count()
    total_responders = User.objects.filter(user_role=User.RoleChoices.RESPONDER).count()

    month_start = today.replace(day=1)
    month_count = CallSession.objects.filter(session_call_date__gte=month_start, session_call_date__lte=today).count()
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    last_count = CallSession.objects.filter(
        session_call_date__gte=last_month_start, session_call_date__lte=last_month_end
    ).count()
    if last_count and month_count >= last_count * 1.15:
        bump = round((month_count - last_count) * 100 / last_count)
        ai = {"status": "Surge Alert", "message": f"Expected +{bump}% increase this month. Review staffing levels."}
    else:
        ai = {"status": "Stable", "message": f"{month_count} call{'s' if month_count != 1 else ''} so far this month. Maintain current staffing."}

    return {
        "period": period,
        "period_options": ADMIN_PERIOD_OPTIONS,
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "range_label": range_label,
        "total": total,
        "trend": trend,
        "high": high,
        "escalation": escalation,
        "active_responders": active_responders,
        "total_responders": total_responders,
        "duration_label": duration_label,
        "duration_pct": duration_pct,
        "referrals": referrals,
        "referral_rate": referral_rate,
        "alerts": _alerts(in_period),
        "ai": ai,
    }
