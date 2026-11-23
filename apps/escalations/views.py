from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.callers.models import CallSession
from apps.dashboard.views import _get_session_user
from apps.escalations import services
from apps.escalations.forms import (
    AssessmentForm,
    AssignmentForm,
    CancelForm,
    EscalationCreateForm,
    NoteForm,
)
from apps.pagination import paginate


def _home_for(user):
    if user.user_role == User.RoleChoices.ADMIN:
        return redirect('dashboard:admin_index')
    if user.user_role == User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL:
        return redirect('dashboard:professional_index')
    return redirect('dashboard:index')


def _active_mhp_queryset():
    return User.objects.filter(
        user_role=User.RoleChoices.MENTAL_HEALTH_PROFESSIONAL,
        user_status=User.StatusChoices.ACTIVE,
    ).order_by('user_first_name', 'user_last_name')


def _load_escalation(request, escalation_id):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return None, None, redirect_response

    try:
        escalation = services.get_escalation_for_user(escalation_id, user)
    except services.EscalationPermissionError as exc:
        messages.error(request, str(exc))
        return user, None, redirect('escalations:queue')

    if escalation is None:
        messages.error(request, "Escalation not found.")
        return user, None, redirect('escalations:queue')

    return user, escalation, None


def queue(request):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response

    filters = {
        'status': request.GET.get('status', ''),
        'urgency': request.GET.get('urgency', ''),
        'search': request.GET.get('search', ''),
    }
    page_obj, querystring = paginate(
        request,
        services.list_escalations(user, filters),
        page_param='esc_page',
    )

    return render(request, 'escalations/queue.html', {
        'user': user,
        'page_obj': page_obj,
        'querystring': querystring,
        'filters': filters,
        'counts': services.escalation_counts(user),
        'status_choices': services.CallerEscalation.StatusChoices.choices,
        'urgency_choices': services.CallerEscalation.UrgencyChoices.choices,
    })


def new_escalation(request):
    user, redirect_response = _get_session_user(request)
    if redirect_response:
        return redirect_response

    if not services.can_create_escalation(user):
        messages.error(request, "Your role cannot initiate an escalation.")
        return _home_for(user)

    session_id = (request.GET.get('session_id') or request.POST.get('session_id') or '').strip()
    session = CallSession.objects.filter(pk=session_id).first()
    if session is None:
        messages.error(request, "Select a saved call session to escalate.")
        return redirect('documentation:master_history')

    mhp_queryset = _active_mhp_queryset()
    if request.method == 'POST':
        form = EscalationCreateForm(request.POST)
        form.fields['assigned_to'].queryset = mhp_queryset

        if form.is_valid():
            assigned_to = form.cleaned_data.get('assigned_to')
            try:
                escalation = services.create_escalation(
                    session=session,
                    requested_by=user,
                    observations=form.cleaned_data['observations'],
                    urgency=form.cleaned_data['urgency'],
                    assigned_to=assigned_to,
                )
                messages.success(request, f"Escalation {escalation.display_id} created.")
                return redirect('escalations:detail', escalation_id=escalation.escalation_id)
            except services.EscalationError as exc:
                messages.error(request, str(exc))
    else:
        form = EscalationCreateForm(initial={
            'urgency': services.CallerEscalation.UrgencyChoices.ROUTINE,
        })
        form.fields['assigned_to'].queryset = mhp_queryset

    return render(request, 'escalations/new.html', {
        'user': user,
        'form': form,
        'session': session,
    })


def detail(request, escalation_id):
    user, escalation, redirect_response = _load_escalation(request, escalation_id)
    if redirect_response:
        return redirect_response

    context = services.get_case_context(escalation)
    assignment_form = AssignmentForm()
    assignment_form.fields['assigned_to'].queryset = _active_mhp_queryset()

    context.update({
        'user': user,
        'assessments': escalation.assessments.select_related('assessed_by'),
        'events': escalation.events.select_related('actor'),
        'can_assign': services.can_assign_escalation(user, escalation),
        'can_acknowledge': services.can_acknowledge_escalation(user, escalation),
        'can_request_info': services.can_request_info(user, escalation),
        'can_complete': services.can_complete_escalation(user, escalation),
        'can_provide_info': services.can_provide_info(user, escalation),
        'can_cancel': services.can_cancel_escalation(user, escalation),
        'assignment_form': assignment_form,
        'note_form': NoteForm(),
        'assessment_form': AssessmentForm(),
        'cancel_form': CancelForm(),
    })
    return render(request, 'escalations/detail.html', context)


@require_POST
def assign(request, escalation_id):
    user, escalation, redirect_response = _load_escalation(request, escalation_id)
    if redirect_response:
        return redirect_response

    if not services.can_assign_escalation(user, escalation):
        messages.error(request, "You cannot assign this escalation.")
        return redirect('escalations:detail', escalation_id=escalation.escalation_id)

    form = AssignmentForm(request.POST)
    form.fields['assigned_to'].queryset = _active_mhp_queryset()
    if form.is_valid():
        try:
            services.assign_escalation(escalation, user, form.cleaned_data['assigned_to'])
            messages.success(request, "Escalation assigned.")
            return redirect('escalations:detail', escalation_id=escalation.escalation_id)
        except services.EscalationError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Select a valid mental health professional.")

    return redirect('escalations:detail', escalation_id=escalation.escalation_id)


@require_POST
def acknowledge(request, escalation_id):
    user, escalation, redirect_response = _load_escalation(request, escalation_id)
    if redirect_response:
        return redirect_response

    if not services.can_acknowledge_escalation(user, escalation):
        messages.error(request, "You cannot acknowledge this escalation.")
        return redirect('escalations:detail', escalation_id=escalation.escalation_id)

    try:
        services.acknowledge_escalation(escalation, user)
        messages.success(request, "Escalation is now under review.")
    except services.EscalationError as exc:
        messages.error(request, str(exc))

    return redirect('escalations:detail', escalation_id=escalation.escalation_id)


@require_POST
def request_info(request, escalation_id):
    user, escalation, redirect_response = _load_escalation(request, escalation_id)
    if redirect_response:
        return redirect_response

    if not services.can_request_info(user, escalation):
        messages.error(request, "You cannot request information on this escalation.")
        return redirect('escalations:detail', escalation_id=escalation.escalation_id)

    form = NoteForm(request.POST)
    if form.is_valid():
        try:
            services.request_info(escalation, user, form.cleaned_data['note'])
            messages.success(request, "Information request recorded.")
            return redirect('escalations:detail', escalation_id=escalation.escalation_id)
        except services.EscalationError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "A note is required.")

    return redirect('escalations:detail', escalation_id=escalation.escalation_id)


@require_POST
def provide_info(request, escalation_id):
    user, escalation, redirect_response = _load_escalation(request, escalation_id)
    if redirect_response:
        return redirect_response

    if not services.can_provide_info(user, escalation):
        messages.error(request, "You cannot provide information on this escalation.")
        return redirect('escalations:detail', escalation_id=escalation.escalation_id)

    form = NoteForm(request.POST)
    if form.is_valid():
        try:
            services.provide_info(escalation, user, form.cleaned_data['note'])
            messages.success(request, "Information recorded.")
            return redirect('escalations:detail', escalation_id=escalation.escalation_id)
        except services.EscalationError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "A note is required.")

    return redirect('escalations:detail', escalation_id=escalation.escalation_id)


@require_POST
def complete(request, escalation_id):
    user, escalation, redirect_response = _load_escalation(request, escalation_id)
    if redirect_response:
        return redirect_response

    if not services.can_complete_escalation(user, escalation):
        messages.error(request, "You cannot complete this escalation.")
        return redirect('escalations:detail', escalation_id=escalation.escalation_id)

    form = AssessmentForm(request.POST)
    if form.is_valid():
        try:
            services.complete_escalation(
                escalation,
                user,
                findings=form.cleaned_data['findings'],
                recommendations=form.cleaned_data['recommendations'],
                follow_up=form.cleaned_data['follow_up'],
            )
            messages.success(request, "Assessment saved and escalation completed.")
            return redirect('escalations:detail', escalation_id=escalation.escalation_id)
        except services.EscalationError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Complete all assessment fields.")

    return redirect('escalations:detail', escalation_id=escalation.escalation_id)


@require_POST
def cancel(request, escalation_id):
    user, escalation, redirect_response = _load_escalation(request, escalation_id)
    if redirect_response:
        return redirect_response

    if not services.can_cancel_escalation(user, escalation):
        messages.error(request, "You cannot cancel this escalation.")
        return redirect('escalations:detail', escalation_id=escalation.escalation_id)

    form = CancelForm(request.POST)
    if form.is_valid():
        try:
            services.cancel_escalation(escalation, user, note=form.cleaned_data['note'])
            messages.success(request, "Escalation cancelled.")
            return redirect('escalations:detail', escalation_id=escalation.escalation_id)
        except services.EscalationError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Invalid cancellation request.")

    return redirect('escalations:detail', escalation_id=escalation.escalation_id)
