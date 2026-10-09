import json
import calendar
from datetime import date
from dateutil.relativedelta import relativedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Count, Case, When, Q
from django.utils import timezone
from .models import Report
from apps.accounts.models import User
from apps.callers.models import CallSession, Caller

def generate_view(request):
    user_id = request.session.get('user_id')
    if not user_id:
        messages.error(request, "You must be logged in to access this page.")
        return redirect('accounts:login')
        
    if request.session.get('user_role') != 'Admin':
        messages.error(request, "You do not have permission to view reports.")
        return redirect('dashboard:index')

    if request.method == 'POST':
        action = request.POST.get('action')
        admin_user = User.objects.get(pk=user_id)
        
        # --- Handle Report Creation ---
        if action == 'create_report':
            title = request.POST.get('report_title')
            r_type = request.POST.get('report_type')
            start_str = request.POST.get('start_period') 
            end_str = request.POST.get('end_period')     
            
            full_title = f"{title} | {start_str} to {end_str}"
            
            Report.objects.create(
                report_title=full_title,
                report_generated_date=timezone.now().date(),
                report_type=r_type,
                generated_by=admin_user
            )
            messages.success(request, f'Report "{title}" generated successfully.')
            return redirect('reports:generate')
            
        # --- Handle Report Editing ---
        elif action == 'edit_report':
            report_id = request.POST.get('report_id')
            new_title = request.POST.get('report_title')
            r_type = request.POST.get('report_type')
            
            report = get_object_or_404(Report, pk=report_id)
            
            # Preserve the hidden target dates when saving the new title
            if " | " in report.report_title:
                _, target_str = report.report_title.split(" | ", 1)
                report.report_title = f"{new_title} | {target_str}"
            else:
                report.report_title = new_title
                
            report.report_type = r_type
            report.save()
            
            messages.success(request, 'Report updated successfully.')
            return redirect('reports:generate')

    reports = Report.objects.all().order_by('-report_generated_date', '-report_id')

    # Clean titles and extract the Target Year for the frontend UI filter
    for r in reports:
        if " | " in r.report_title:
            parts = r.report_title.split(" | ", 1)
            r.display_title = parts[0]
            try:
                date_str = parts[1]
                r.target_year = date_str.split('-')[0] # Grabs the start year (e.g., '2026' from '2026-01')
                
                if " to " in date_str:
                    s, e = date_str.split(" to ")
                    sy, sm = int(s.split('-')[0]), int(s.split('-')[1])
                    ey, em = int(e.split('-')[0]), int(e.split('-')[1])
                    
                    if s == e:
                        r.target_period = f"{calendar.month_abbr[sm]} {sy}"
                    else:
                        r.target_period = f"{calendar.month_abbr[sm]} {sy} - {calendar.month_abbr[em]} {ey}"
                else:
                    r.target_period = date_str
            except:
                r.target_year = r.report_generated_date.year
                r.target_period = parts[1]
        else:
            r.display_title = r.report_title
            r.target_year = r.report_generated_date.year
            r.target_period = ""
    
    return render(request, 'reports/generate.html', {
        'reports': reports,
        'report_types': Report.ReportTypeChoices.choices,
    })


def export_pdf_view(request, report_id):
    if not request.session.get('user_id'):
        return redirect('accounts:login')

    report = get_object_or_404(Report, pk=report_id)
    
    # --- PARSE THE CUSTOM DATE RANGE ---
    if " | " in report.report_title:
        clean_title, date_range = report.report_title.split(" | ", 1)
        if " to " in date_range:
            start_str, end_str = date_range.split(" to ")
        else:
            start_str = date_range
            end_str = date_range
            
        start_year, start_month = int(start_str.split('-')[0]), int(start_str.split('-')[1])
        end_year, end_month = int(end_str.split('-')[0]), int(end_str.split('-')[1])
        
        start_date = date(start_year, start_month, 1)
        last_day = calendar.monthrange(end_year, end_month)[1]
        end_date = date(end_year, end_month, last_day)
    else:
        clean_title = report.report_title
        start_year = report.report_generated_date.year
        start_date = date(start_year, 1, 1)
        end_date = date(start_year, 12, 31)
        start_str = f"{start_year}-01"
        end_str = f"{start_year}-12"

    is_monthly = (start_str == end_str)

    # --- FILTER BY DATE RANGE ---
    sessions = CallSession.objects.filter(session_call_date__range=(start_date, end_date))
    total_calls = sessions.count()

    def calculate_growth(current_count, previous_count):
        if previous_count == 0:
            return "+100.00%" if current_count > 0 else "0.00%"
        growth = ((current_count - previous_count) / previous_count) * 100
        return f"{growth:+.2f}%"

    if is_monthly:
        prev_month_date = start_date - relativedelta(months=1)
        prev_month_calls = CallSession.objects.filter(
            session_call_date__year=prev_month_date.year, 
            session_call_date__month=prev_month_date.month
        ).count()
        mom_increase = calculate_growth(total_calls, prev_month_calls)

        last_year_date = start_date - relativedelta(years=1)
        last_year_calls = CallSession.objects.filter(
            session_call_date__year=last_year_date.year, 
            session_call_date__month=last_year_date.month
        ).count()
        yoy_increase = calculate_growth(total_calls, last_year_calls)
        
        current_period_label = start_date.strftime('%B %Y').upper()
        previous_month_label = prev_month_date.strftime('%B %Y').upper()
        same_month_last_year_label = last_year_date.strftime('%B %Y').upper()
        display_period = current_period_label
    else:
        prev_start = start_date - relativedelta(years=1)
        prev_end = end_date - relativedelta(years=1)
        prev_range_calls = CallSession.objects.filter(session_call_date__range=(prev_start, prev_end)).count()
        annual_increase = calculate_growth(total_calls, prev_range_calls)
        
        if start_date.year == end_date.year and start_date.month == 1 and end_date.month == 12:
            current_period_label = f"YEAR {start_date.year}"
            previous_period_label = f"YEAR {prev_start.year}"
        else:
            current_period_label = f"{start_date.strftime('%B %Y')} - {end_date.strftime('%B %Y')}".upper()
            previous_period_label = f"{prev_start.strftime('%B %Y')} - {prev_end.strftime('%B %Y')}".upper()
            
        display_period = current_period_label

    age_data = sessions.aggregate(
        a14_17=Count(Case(When(caller__caller_age__range=(14, 17), then=1))),
        a18_21=Count(Case(When(caller__caller_age__range=(18, 21), then=1))),
        a22_25=Count(Case(When(caller__caller_age__range=(22, 25), then=1))),
        a26_29=Count(Case(When(caller__caller_age__range=(26, 29), then=1))),
        a30_33=Count(Case(When(caller__caller_age__range=(30, 33), then=1))),
        a34_37=Count(Case(When(caller__caller_age__range=(34, 37), then=1))),
        a38_41=Count(Case(When(caller__caller_age__range=(38, 41), then=1))),
        a42_up=Count(Case(When(caller__caller_age__gte=42, then=1))),
        a_na=Count(Case(When(caller__caller_age__isnull=True, then=1))),
    )
    age_values = [age_data['a14_17'], age_data['a18_21'], age_data['a22_25'], age_data['a26_29'], age_data['a30_33'], age_data['a34_37'], age_data['a38_41'], age_data['a42_up'], age_data['a_na']]

    gender_counts = sessions.values('caller__caller_gender').annotate(c=Count('session_id'))
    g_map = {g['caller__caller_gender']: g['c'] for g in gender_counts}
    gender_values = [g_map.get('Male', 0), g_map.get('Female', 0), g_map.get('LGBTQ+', 0)]

    risk_counts = sessions.values('session_risk_assessment').annotate(c=Count('session_id'))
    r_map = {r['session_risk_assessment']: r['c'] for r in risk_counts}
    risk_values = [
        r_map.get('High', 0) + r_map.get('High Risk', 0),
        r_map.get('Medium', 0) + r_map.get('Medium Risk', 0) + r_map.get('Moderate Risk', 0),
        r_map.get('Low', 0) + r_map.get('Low Risk', 0)
    ]

    civil_counts = sessions.values('caller__caller_civil_status').annotate(c=Count('session_id'))
    c_map = {c['caller__caller_civil_status']: c['c'] for c in civil_counts}
    civil_labels = ['Married', 'Separated', 'Single', 'Single (Living in)', 'Widowed', 'N/A']
    civil_values = [c_map.get(lbl, 0) for lbl in civil_labels]

    reason_counts = sessions.values('session_reason_for_calling').annotate(c=Count('session_id')).order_by('-c')[:10]
    reasons_labels = [r['session_reason_for_calling'] or "Unspecified" for r in reason_counts]
    reasons_values = [r['c'] for r in reason_counts]

    interv_counts = sessions.values('session_intervention').annotate(c=Count('session_id')).order_by('-c')[:6]
    interventions_labels = [i['session_intervention'] or "None" for i in interv_counts]
    interventions_values = [i['c'] for i in interv_counts]

    shift_counts = sessions.values('shift__shift_start_time', 'shift__shift_end_time').annotate(c=Count('session_id')).order_by('shift__shift_start_time')
    shift_labels, shift_values = [], []
    for sc in shift_counts:
        if sc['shift__shift_start_time'] and sc['shift__shift_end_time']:
            start = sc['shift__shift_start_time'].strftime('%I:%M %p').lstrip('0')
            end = sc['shift__shift_end_time'].strftime('%I:%M %p').lstrip('0')
            shift_labels.append(f"{start} - {end}")
        else:
            shift_labels.append("Unspecified")
        shift_values.append(sc['c'])

    if is_monthly:
        w1 = sessions.filter(session_call_date__day__lte=7).count()
        w2 = sessions.filter(session_call_date__day__range=(8, 14)).count()
        w3 = sessions.filter(session_call_date__day__range=(15, 21)).count()
        w4 = sessions.filter(session_call_date__day__gte=22).count()
        
        monthly_data = {
            'report_title': clean_title,
            'report_month_title': f"{start_date.strftime('%B %Y')} Report",
            'period_label': display_period,
            'current_period_label': current_period_label,
            'weekly_labels': json.dumps(['Week 1', 'Week 2', 'Week 3', 'Week 4']),
            'weekly_values': json.dumps([w1, w2, w3, w4]),
            'mom_increase': mom_increase,
            'previous_month_label': previous_month_label,
            'yoy_increase': yoy_increase,
            'same_month_last_year_label': same_month_last_year_label,
            'age_labels': json.dumps(['14-17', '18-21', '22-25', '26-29', '30-33', '34-37', '38-41', '42 AND ABOVE', 'N/A']),
            'age_values': json.dumps(age_values),
            'gender_labels': json.dumps(['MALE', 'FEMALE', 'LGBTQ+']),
            'gender_values': json.dumps(gender_values),
            'risk_labels': json.dumps(['HIGH RISK', 'MODERATE RISK', 'LOW RISK']),
            'risk_values': json.dumps(risk_values),
            'civil_labels': json.dumps([l.upper() for l in civil_labels]),
            'civil_values': json.dumps(civil_values),
            'shift_labels': json.dumps(shift_labels), 
            'shift_values': json.dumps(shift_values), 
            'reasons_labels': json.dumps([l.upper() for l in reasons_labels]),
            'reasons_values': json.dumps(reasons_values),
            'sources_labels': json.dumps(['ONLINE', 'REFERRAL', 'OTHER']), 
            'sources_values': json.dumps([total_calls, 0, 0]),
            'interventions_labels': json.dumps([l.upper() for l in interventions_labels]),
            'interventions_values': json.dumps(interventions_values),
        }
        return render(request, 'reports/monthly_pdf_report.html', monthly_data)

    else:
        years = [end_year - i for i in range(4, -1, -1)]
        annual_vals = [CallSession.objects.filter(session_call_date__year=y).count() for y in years]
        
        annual_data = {
            'report_title': clean_title,
            'report_year': display_period, 
            'period_label': display_period,
            'shift_period_label': display_period,
            'annual_labels': json.dumps([str(y) for y in years]),
            'annual_values': json.dumps(annual_vals),
            'annual_increase': annual_increase, 
            'current_period_label': current_period_label,
            'previous_period_label': previous_period_label,
            'age_labels': json.dumps(['14-17', '18-21', '22-25', '26-29', '30-33', '34-37', '38-41', '42 AND ABOVE', 'N/A']),
            'age_values': json.dumps(age_values),
            'gender_labels': json.dumps(['MALE', 'FEMALE', 'LGBTQ+']),
            'gender_values': json.dumps(gender_values),
            'risk_labels': json.dumps(['HIGH RISK', 'MODERATE RISK', 'LOW RISK']),
            'risk_values': json.dumps(risk_values),
            'civil_labels': json.dumps([l.upper() for l in civil_labels]),
            'civil_values': json.dumps(civil_values),
            'shift_labels': json.dumps(shift_labels),
            'shift_values': json.dumps(shift_values),
            'reasons_labels': json.dumps([l.upper() for l in reasons_labels]),
            'reasons_values': json.dumps(reasons_values),
            'sources_labels': json.dumps(['ONLINE', 'REFERRAL', 'OTHER']), 
            'sources_values': json.dumps([total_calls, 0, 0]),
            'interventions_labels': json.dumps([l.upper() for l in interventions_labels]),
            'interventions_values': json.dumps(interventions_values),
        }
        return render(request, 'reports/pdf_report.html', annual_data)