from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User
from apps.callers.models import CallSession
from apps.escalations.models import (
    CallerEscalation,
    EscalationAssessment,
    EscalationEvent,
)


class EscalationError(ValueError):
    pass


class EscalationPermissionError(EscalationError):
    pass


class EscalationConflictError(EscalationError):
    pass


class InvalidTransitionError(EscalationError):
    pass


ACTIVE_STATUSES = (
    CallerEscalation.StatusChoices.PENDING,
    CallerEscalation.StatusChoices.ASSIGNED,
    CallerEscalation.StatusChoices.UNDER_REVIEW,
    CallerEscalation.StatusChoices.NEEDS_INFO,
)

ALLOWED_TRANSITIONS = {
    CallerEscalation.StatusChoices.PENDING: {
        CallerEscalation.StatusChoices.ASSIGNED,
        CallerEscalation.StatusChoices.CANCELLED,
    },
    CallerEscalation.StatusChoices.ASSIGNED: {
        CallerEscalation.StatusChoices.UNDER_REVIEW,
        CallerEscalation.StatusChoices.CANCELLED,
    },
    CallerEscalation.StatusChoices.UNDER_REVIEW: {
        CallerEscalation.StatusChoices.NEEDS_INFO,
        CallerEscalation.StatusChoices.COMPLETED,
        CallerEscalation.StatusChoices.CANCELLED,
    },
    CallerEscalation.StatusChoices.NEEDS_INFO: {
        CallerEscalation.StatusChoices.UNDER_REVIEW,
        CallerEscalation.StatusChoices.CANCELLED,
    },
    CallerEscalation.StatusChoices.COMPLETED: set(),
    CallerEscalation.StatusChoices.CANCELLED: set(),
}


def _ensure_active_role(user, *roles):
    if not user or user.user_status != User.StatusChoices.ACTIVE:
        raise EscalationPermissionError("The user account is not active.")
    if roles and user.user_role not in roles:
        raise EscalationPermissionError("This user does not have the required role.")


def _ensure_requester(user):
    _ensure_active_role(
        user,
        User.RoleChoices.RESPONDER,
        User.RoleChoices.ADMIN,
    )


def _ensure_admin(user):
    _ensure_active_role(user, User.RoleChoices.ADMIN)


def _ensure_mhp(user):
    _ensure_active_role(user, User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL)


def _ensure_assignee(user):
    _ensure_mhp(user)


def _ensure_transition(escalation, new_status):
    if new_status not in ALLOWED_TRANSITIONS.get(escalation.status, set()):
        raise InvalidTransitionError(
            f"Cannot change an escalation from {escalation.status} to {new_status}."
        )


def _record_event(escalation, actor, event_type, from_status=None, to_status=None, note=None):
    return EscalationEvent.objects.create(
        escalation=escalation,
        actor=actor,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        note=note,
    )


def can_view_escalation(user, escalation):
    if not user or user.user_status != User.StatusChoices.ACTIVE:
        return False
    if user.user_role == User.RoleChoices.ADMIN:
        return True
    if user.user_role == User.RoleChoices.RESPONDER:
        return escalation.requested_by_id == user.user_id
    if user.user_role == User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL:
        return escalation.assigned_to_id == user.user_id
    return False


def can_create_escalation(user):
    return bool(
        user
        and user.user_status == User.StatusChoices.ACTIVE
        and user.user_role in (User.RoleChoices.RESPONDER, User.RoleChoices.ADMIN)
    )


def can_assign_escalation(user, escalation):
    return bool(
        user
        and user.user_status == User.StatusChoices.ACTIVE
        and user.user_role == User.RoleChoices.ADMIN
        and CallerEscalation.StatusChoices.ASSIGNED in ALLOWED_TRANSITIONS.get(escalation.status, set())
    )


def can_acknowledge_escalation(user, escalation):
    return bool(
        user
        and user.user_status == User.StatusChoices.ACTIVE
        and user.user_role == User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL
        and escalation.assigned_to_id == user.user_id
        and CallerEscalation.StatusChoices.UNDER_REVIEW in ALLOWED_TRANSITIONS.get(escalation.status, set())
    )


def can_request_info(user, escalation):
    return bool(
        user
        and user.user_status == User.StatusChoices.ACTIVE
        and user.user_role == User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL
        and escalation.assigned_to_id == user.user_id
        and escalation.status == CallerEscalation.StatusChoices.UNDER_REVIEW
    )


def can_complete_escalation(user, escalation):
    return bool(
        user
        and user.user_status == User.StatusChoices.ACTIVE
        and user.user_role == User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL
        and escalation.assigned_to_id == user.user_id
        and CallerEscalation.StatusChoices.COMPLETED in ALLOWED_TRANSITIONS.get(escalation.status, set())
    )


def can_provide_info(user, escalation):
    return bool(
        user
        and user.user_status == User.StatusChoices.ACTIVE
        and escalation.status == CallerEscalation.StatusChoices.NEEDS_INFO
        and (
            user.user_role == User.RoleChoices.ADMIN
            or escalation.requested_by_id == user.user_id
        )
    )


def can_cancel_escalation(user, escalation):
    return bool(
        user
        and user.user_status == User.StatusChoices.ACTIVE
        and (
            user.user_role == User.RoleChoices.ADMIN
            or escalation.requested_by_id == user.user_id
        )
        and escalation.status in ACTIVE_STATUSES
    )


def visible_escalations(user):
    if not user or user.user_status != User.StatusChoices.ACTIVE:
        return CallerEscalation.objects.none()
    if user.user_role == User.RoleChoices.ADMIN:
        return CallerEscalation.objects.all()
    if user.user_role == User.RoleChoices.RESPONDER:
        return CallerEscalation.objects.filter(requested_by=user)
    if user.user_role == User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL:
        return CallerEscalation.objects.filter(assigned_to=user)
    return CallerEscalation.objects.none()


def list_escalations(user, filters=None):
    filters = filters or {}
    queryset = visible_escalations(user).select_related(
        'session',
        'session__caller',
        'session__user',
        'requested_by',
        'assigned_to',
    )

    status = filters.get('status')
    urgency = filters.get('urgency')
    search = (filters.get('search') or '').strip()

    if status:
        queryset = queryset.filter(status=status)
    if urgency:
        queryset = queryset.filter(urgency=urgency)
    if search:
        queryset = queryset.filter(
            Q(session__session_id__icontains=search)
            | Q(session__caller__caller_name__icontains=search)
            | Q(session__caller__caller_number__icontains=search)
        )

    return queryset.order_by('-created_at')


def escalation_counts(user):
    queryset = visible_escalations(user)
    counts = {
        'pending': queryset.filter(status=CallerEscalation.StatusChoices.PENDING).count(),
        'assigned': queryset.filter(status=CallerEscalation.StatusChoices.ASSIGNED).count(),
        'under_review': queryset.filter(status=CallerEscalation.StatusChoices.UNDER_REVIEW).count(),
        'needs_info': queryset.filter(status=CallerEscalation.StatusChoices.NEEDS_INFO).count(),
        'completed': queryset.filter(status=CallerEscalation.StatusChoices.COMPLETED).count(),
        'cancelled': queryset.filter(status=CallerEscalation.StatusChoices.CANCELLED).count(),
        'all': queryset.count(),
        'active': queryset.filter(status__in=ACTIVE_STATUSES).count(),
    }
    return counts


def get_escalation_for_user(escalation_id, user):
    escalation = (
        CallerEscalation.objects
        .select_related(
            'session',
            'session__caller',
            'session__user',
            'requested_by',
            'assigned_to',
        )
        .filter(escalation_id=escalation_id)
        .first()
    )
    if escalation is None:
        return None
    if not can_view_escalation(user, escalation):
        raise EscalationPermissionError("You do not have access to this escalation.")
    return escalation


@transaction.atomic
def create_escalation(session, requested_by, observations, urgency, assigned_to=None):
    _ensure_requester(requested_by)
    if assigned_to is not None:
        _ensure_assignee(assigned_to)

    observations = (observations or '').strip()
    if not observations:
        raise EscalationError("Observations are required.")

    if urgency not in CallerEscalation.UrgencyChoices.values:
        raise EscalationError("Invalid urgency.")

    if CallerEscalation.objects.filter(session=session, status__in=ACTIVE_STATUSES).exists():
        raise EscalationConflictError("This call session already has an active escalation.")

    initial_status = (
        CallerEscalation.StatusChoices.ASSIGNED
        if assigned_to is not None
        else CallerEscalation.StatusChoices.PENDING
    )
    now = timezone.now()

    escalation = CallerEscalation.objects.create(
        session=session,
        requested_by=requested_by,
        assigned_to=assigned_to,
        status=initial_status,
        urgency=urgency,
        observations=observations,
        assigned_at=now if assigned_to is not None else None,
    )
    _record_event(
        escalation,
        requested_by,
        EscalationEvent.EventTypeChoices.CREATED,
        to_status=initial_status,
    )
    if assigned_to is not None:
        _record_event(
            escalation,
            requested_by,
            EscalationEvent.EventTypeChoices.ASSIGNED,
            from_status=CallerEscalation.StatusChoices.PENDING,
            to_status=CallerEscalation.StatusChoices.ASSIGNED,
        )
    return escalation


@transaction.atomic
def assign_escalation(escalation, actor, assignee):
    _ensure_admin(actor)
    _ensure_assignee(assignee)
    _ensure_transition(escalation, CallerEscalation.StatusChoices.ASSIGNED)

    from_status = escalation.status
    escalation.assigned_to = assignee
    escalation.assigned_at = timezone.now()
    escalation.status = CallerEscalation.StatusChoices.ASSIGNED
    escalation.save()
    _record_event(
        escalation,
        actor,
        EscalationEvent.EventTypeChoices.ASSIGNED,
        from_status=from_status,
        to_status=CallerEscalation.StatusChoices.ASSIGNED,
    )
    return escalation


@transaction.atomic
def acknowledge_escalation(escalation, actor):
    _ensure_mhp(actor)
    if escalation.assigned_to_id != actor.user_id:
        raise EscalationPermissionError("Only the assigned professional can review this escalation.")
    _ensure_transition(escalation, CallerEscalation.StatusChoices.UNDER_REVIEW)

    from_status = escalation.status
    escalation.status = CallerEscalation.StatusChoices.UNDER_REVIEW
    escalation.save()
    _record_event(
        escalation,
        actor,
        EscalationEvent.EventTypeChoices.ACKNOWLEDGED,
        from_status=from_status,
        to_status=CallerEscalation.StatusChoices.UNDER_REVIEW,
    )
    return escalation


@transaction.atomic
def request_info(escalation, actor, note):
    _ensure_mhp(actor)
    if escalation.assigned_to_id != actor.user_id:
        raise EscalationPermissionError("Only the assigned professional can request information.")
    _ensure_transition(escalation, CallerEscalation.StatusChoices.NEEDS_INFO)

    note = (note or '').strip()
    if not note:
        raise EscalationError("A note is required when requesting information.")

    from_status = escalation.status
    escalation.status = CallerEscalation.StatusChoices.NEEDS_INFO
    escalation.save()
    _record_event(
        escalation,
        actor,
        EscalationEvent.EventTypeChoices.INFO_REQUESTED,
        from_status=from_status,
        to_status=CallerEscalation.StatusChoices.NEEDS_INFO,
        note=note,
    )
    return escalation


@transaction.atomic
def provide_info(escalation, actor, note):
    _ensure_requester(actor)
    if escalation.requested_by_id != actor.user_id and actor.user_role != User.RoleChoices.ADMIN:
        raise EscalationPermissionError("Only the requester or a manager can provide information.")
    _ensure_transition(escalation, CallerEscalation.StatusChoices.UNDER_REVIEW)

    note = (note or '').strip()
    if not note:
        raise EscalationError("A note is required when providing information.")

    from_status = escalation.status
    escalation.status = CallerEscalation.StatusChoices.UNDER_REVIEW
    escalation.save()
    _record_event(
        escalation,
        actor,
        EscalationEvent.EventTypeChoices.INFO_PROVIDED,
        from_status=from_status,
        to_status=CallerEscalation.StatusChoices.UNDER_REVIEW,
        note=note,
    )
    return escalation


@transaction.atomic
def complete_escalation(escalation, actor, findings, recommendations, follow_up):
    _ensure_mhp(actor)
    if escalation.assigned_to_id != actor.user_id:
        raise EscalationPermissionError("Only the assigned professional can complete this escalation.")
    _ensure_transition(escalation, CallerEscalation.StatusChoices.COMPLETED)

    findings = (findings or '').strip()
    recommendations = (recommendations or '').strip()
    if not findings or not recommendations:
        raise EscalationError("Findings and recommendations are required.")
    if follow_up not in EscalationAssessment.FollowUpChoices.values:
        raise EscalationError("Invalid follow-up option.")

    assessment = EscalationAssessment.objects.create(
        escalation=escalation,
        assessed_by=actor,
        findings=findings,
        recommendations=recommendations,
        follow_up=follow_up,
    )

    from_status = escalation.status
    escalation.status = CallerEscalation.StatusChoices.COMPLETED
    escalation.resolved_at = timezone.now()
    escalation.save()
    _record_event(
        escalation,
        actor,
        EscalationEvent.EventTypeChoices.ASSESSED,
        from_status=from_status,
        to_status=CallerEscalation.StatusChoices.COMPLETED,
    )
    return escalation, assessment


@transaction.atomic
def cancel_escalation(escalation, actor, note=None):
    _ensure_active_role(actor)
    if actor.user_role != User.RoleChoices.ADMIN and escalation.requested_by_id != actor.user_id:
        raise EscalationPermissionError("Only the requester or a manager can cancel this escalation.")
    _ensure_transition(escalation, CallerEscalation.StatusChoices.CANCELLED)

    from_status = escalation.status
    escalation.status = CallerEscalation.StatusChoices.CANCELLED
    escalation.resolved_at = timezone.now()
    escalation.save()
    _record_event(
        escalation,
        actor,
        EscalationEvent.EventTypeChoices.CANCELLED,
        from_status=from_status,
        to_status=CallerEscalation.StatusChoices.CANCELLED,
        note=note,
    )
    return escalation


def mask_phone(number):
    if not number:
        return ''
    digits = ''.join(character for character in number if character.isdigit())
    if len(digits) <= 4:
        return '*' * len(digits)
    return f"***-***-{digits[-4:]}"


def get_case_context(escalation):
    from apps.documentation.views import _attach_referrals, _attach_transcripts

    session = escalation.session
    _attach_transcripts([session])
    _attach_referrals([session])

    prior_sessions = (
        CallSession.objects
        .filter(caller=session.caller)
        .exclude(pk=session.pk)
        .select_related('user')
        .order_by('-session_call_date', '-session_time_called')[:5]
    )

    return {
        'escalation': escalation,
        'session': session,
        'caller': session.caller,
        'transcripts': session.transcript_texts,
        'referral': session.referral,
        'prior_sessions': list(prior_sessions),
        'masked_phone': mask_phone(session.caller.caller_number),
    }
