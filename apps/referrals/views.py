from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.db.models import Q
from django.utils import timezone
from django.contrib import messages
from apps.pagination import paginate
from .models import (
    Institution, InstitutionContact, Professional, ProfessionalContact, Affiliation
)

# --- DETAILED REGION MAPPING ---
REGION_MAP = {
    'NCR': ['Caloocan', 'Las Piñas', 'Makati', 'Malabon', 'Mandaluyong', 'Manila', 'Marikina', 'Muntinlupa', 'Navotas', 'Parañaque', 'Pasay', 'Pasig', 'Quezon City', 'San Juan', 'Taguig', 'Valenzuela', 'NCR', 'Metro Manila'],
    'CAR': ['Abra', 'Apayao', 'Benguet', 'Ifugao', 'Kalinga', 'Mountain Province', 'Baguio', 'Cordillera'],
    'Region I': ['Ilocos Norte', 'Ilocos Sur', 'La Union', 'Pangasinan', 'Region I'],
    'Region II': ['Batanes', 'Cagayan', 'Isabela', 'Nueva Vizcaya', 'Quirino', 'Tuguegarao', 'Region II'],
    'Region III': ['Aurora', 'Bataan', 'Bulacan', 'Nueva Ecija', 'Pampanga', 'Tarlac', 'Zambales', 'Angeles', 'Olongapo', 'Region III'],
    'Region IV-A': ['Batangas', 'Cavite', 'Laguna', 'Quezon', 'Rizal', 'Lucena', 'CALABARZON', 'Region IV-A'],
    'Region IV-B': ['Marinduque', 'Occidental Mindoro', 'Oriental Mindoro', 'Palawan', 'Romblon', 'Puerto Princesa', 'MIMAROPA', 'Region IV-B'],
    'Region V': ['Albay', 'Camarines Norte', 'Camarines Sur', 'Catanduanes', 'Masbate', 'Sorsogon', 'Naga', 'Bicol', 'Region V'],
    'Region VI': ['Aklan', 'Antique', 'Capiz', 'Guimaras', 'Iloilo', 'Ilo ilo', 'Negros Occidental', 'Bacolod', 'Western Visayas', 'Region VI'],
    'Region VII': ['Bohol', 'Cebu', 'Negros Oriental', 'Siquijor', 'Mandaue', 'Lapu-Lapu', 'Central Visayas', 'Region VII'],
    'Region VIII': ['Biliran', 'Eastern Samar', 'Leyte', 'Northern Samar', 'Samar', 'Southern Leyte', 'Ormoc', 'Tacloban', 'Eastern Visayas', 'Region VIII'],
    'Region IX': ['Zamboanga del Norte', 'Zamboanga del Sur', 'Zamboanga Sibugay', 'Zamboanga City', 'Isabela City', 'Zamboanga Peninsula', 'Region IX'],
    'Region X': ['Bukidnon', 'Camiguin', 'Lanao del Norte', 'Misamis Occidental', 'Misamis Oriental', 'Cagayan de Oro', 'Iligan', 'Northern Mindanao', 'Region X'],
    'Region XI': ['Davao de Oro', 'Davao del Norte', 'Davao del Sur', 'Davao Occidental', 'Davao Oriental', 'Davao City', 'Davao Region', 'Region XI'],
    'Region XII': ['Cotabato', 'Sarangani', 'South Cotabato', 'Sultan Kudarat', 'General Santos', 'SOCCSKSARGEN', 'Region XII'],
    'Region XIII': ['Agusan del Norte', 'Agusan del Sur', 'Dinagat Islands', 'Surigao del Norte', 'Surigao del Sur', 'Butuan', 'Caraga', 'Region XIII'],
    'BARMM': ['Basilan', 'Lanao del Sur', 'Maguindanao', 'Maguindanao del Norte', 'Maguindanao del Sur', 'Sulu', 'Tawi-Tawi', 'Cotabato City', 'Bangsamoro', 'BARMM']
}

REGION_CHOICES = [
    ("NCR", "NCR \u2013 Metro Manila"),
    ("CAR", "CAR \u2013 Cordillera Administrative Region"),
    ("Region I", "Region I \u2013 Ilocos Region"),
    ("Region II", "Region II \u2013 Cagayan Valley"),
    ("Region III", "Region III \u2013 Central Luzon"),
    ("Region IV-A", "Region IV-A \u2013 CALABARZON"),
    ("Region IV-B", "Region IV-B \u2013 MIMAROPA"),
    ("Region V", "Region V \u2013 Bicol Region"),
    ("Region VI", "Region VI \u2013 Western Visayas"),
    ("Region VII", "Region VII \u2013 Central Visayas"),
    ("Region VIII", "Region VIII \u2013 Eastern Visayas"),
    ("Region IX", "Region IX \u2013 Zamboanga Peninsula"),
    ("Region X", "Region X \u2013 Northern Mindanao"),
    ("Region XI", "Region XI \u2013 Davao Region"),
    ("Region XII", "Region XII \u2013 SOCCSKSARGEN"),
    ("Region XIII", "Region XIII \u2013 Caraga"),
    ("BARMM", "BARMM \u2013 Bangsamoro"),
]

def _filter_professionals(professionals, search, specialization, region):
    """Apply the shared directory/manager professional filters server-side."""
    search = (search or '').strip()
    if search:
        professionals = professionals.filter(
            Q(professional_name__icontains=search)
            | Q(institution__institution_name__icontains=search)
            | Q(institution__institution_location__icontains=search)
            | Q(professional_location__icontains=search)
            | Q(affiliation__institution__institution_name__icontains=search)
            | Q(affiliation__institution__institution_location__icontains=search)
        ).distinct()

    if specialization and specialization != 'All':
        professionals = professionals.filter(professional_specialization=specialization)

    # Apply Regional Filtering
    if region and region != 'All':
        places = REGION_MAP.get(region, [])
        if places:
            region_query = Q()
            for place in places:
                region_query |= Q(professional_location__icontains=place)
                region_query |= Q(institution__institution_location__icontains=place)
                region_query |= Q(affiliation__institution__institution_location__icontains=place)
            professionals = professionals.filter(region_query).distinct()

    return professionals


def directory_view(request):
    if not request.session.get('user_id'):
        messages.error(request, "You must be logged in to view the directory.")
        return redirect('accounts:login')

    search = request.GET.get('search', '')
    specialization = request.GET.get('specialization', 'All')
    region = request.GET.get('region', 'All')

    # --- 1. INSTITUTIONS TABLE (Read-Only) ---
    institutions = Institution.objects.filter(
        institution_status=Institution.StatusChoices.ACTIVE
    ).prefetch_related('institutioncontact_set').order_by('institution_name')
    
    if search:
        institutions = institutions.filter(
            Q(institution_name__icontains=search)
            | Q(institution_location__icontains=search)
        )
        
    if region != 'All':
        places = REGION_MAP.get(region, [])
        if places:
            region_query = Q()
            for place in places:
                region_query |= Q(institution_location__icontains=place)
            institutions = institutions.filter(region_query).distinct()
            
    inst_page_obj, inst_querystring = paginate(request, institutions, page_param='inst_page')

    # --- 2. PROFESSIONALS TABLE ---
    professionals = Professional.objects.filter(
        professional_status=Professional.StatusChoices.ACTIVE
    ).select_related('institution').prefetch_related(
        'professionalcontact_set', 'affiliation_set__institution'
    )

    professionals = _filter_professionals(
        professionals,
        search,
        specialization,
        region,
    ).order_by('professional_name')

    prof_page_obj, prof_querystring = paginate(request, professionals, page_param='prof_page')

    return render(request, 'referrals/directory.html', {
        'institution_list': inst_page_obj.object_list,
        'inst_page_obj': inst_page_obj,
        'inst_querystring': inst_querystring,
        'professionals': prof_page_obj.object_list,
        'prof_page_obj': prof_page_obj,
        'prof_querystring': prof_querystring,
        'current_search': search,
        'current_specialization': specialization,
        'current_region': region,
        'specialization_choices': Professional.SpecializationChoices.choices,
        'region_choices': REGION_CHOICES,
    })


def manage_view(request):
    if not request.session.get('user_id'):
        messages.error(request, "You must be logged in to access this page.")
        return redirect('accounts:login')
        
    if request.session.get('user_role') != 'Admin':
        messages.error(request, "You do not have permission to manage the directory.")
        return redirect('referrals:directory')

    if request.method == 'POST':
        action = request.POST.get('action')
        
        try:
            # --- ADD / EDIT INSTITUTION ---
            if action == 'save_institution':
                inst_id = request.POST.get('institution_id')
                name = request.POST.get('institution_name').strip()
                location = request.POST.get('institution_location')
                status = request.POST.get('institution_status') or Institution.StatusChoices.ACTIVE
                
                duplicate_query = Institution.objects.filter(institution_name__iexact=name)
                if inst_id:
                    duplicate_query = duplicate_query.exclude(pk=inst_id)
                    
                if duplicate_query.exists():
                    messages.error(request, f'An institution named "{name}" already exists.')
                    return redirect('referrals:manage')

                if inst_id:
                    inst = Institution.objects.get(pk=inst_id)
                    inst.institution_name = name
                    inst.institution_location = location
                    inst.institution_status = status
                    inst.save()
                    inst.institutioncontact_set.all().delete()
                else:
                    inst = Institution.objects.create(
                        institution_name=name, 
                        institution_location=location,
                        institution_status=status
                    )
                
                numbers = request.POST.getlist('contact_number[]')
                types = request.POST.getlist('contact_type[]')
                for num, c_type in zip(numbers, types):
                    if num.strip():
                        InstitutionContact.objects.create(
                            institution=inst,
                            institution_contact_number=num,
                            institution_contact_type=c_type,
                            institution_contact_last_update=timezone.now()
                        )
                
                messages.success(request, 'Institution saved successfully!')
                return redirect('referrals:manage')

            # --- ADD / EDIT PROFESSIONAL ---
            elif action == 'save_professional':
                prof_id = request.POST.get('professional_id')
                name = request.POST.get('professional_name').strip()
                gender = request.POST.get('professional_gender')
                specialization = request.POST.get('professional_specialization')
                location = request.POST.get('professional_location')
                primary_inst_id = request.POST.get('institution_id')
                status = request.POST.get('professional_status') or Professional.StatusChoices.ACTIVE
                
                duplicate_prof_query = Professional.objects.filter(
                    professional_name__iexact=name,
                    professional_specialization=specialization
                )
                if prof_id:
                    duplicate_prof_query = duplicate_prof_query.exclude(pk=prof_id)
                
                if duplicate_prof_query.exists():
                    messages.error(request, f'A professional named "{name}" with this specialization already exists.')
                    return redirect('referrals:manage')

                affil_inst_ids = request.POST.getlist('affiliation_inst_id[]')
                affil_schedules = request.POST.getlist('affiliation_schedule[]')
                
                valid_affil_ids = [aid for aid in affil_inst_ids if aid.strip()]
                
                if len(valid_affil_ids) != len(set(valid_affil_ids)):
                    messages.error(request, 'You cannot add the same institution multiple times in the affiliations list.')
                    return redirect('referrals:manage')

                primary_institution = Institution.objects.get(pk=primary_inst_id) if primary_inst_id else None

                if prof_id:
                    prof = Professional.objects.get(pk=prof_id)
                    prof.professional_name = name
                    prof.professional_gender = gender
                    prof.professional_specialization = specialization
                    prof.professional_location = location
                    prof.institution = primary_institution
                    prof.professional_status = status
                    prof.professional_last_updated = timezone.now()
                    prof.save()
                    
                    prof.professionalcontact_set.all().delete()
                    prof.affiliation_set.all().delete()
                else:
                    prof = Professional.objects.create(
                        professional_name=name,
                        professional_gender=gender,
                        professional_specialization=specialization,
                        professional_location=location,
                        institution=primary_institution,
                        professional_status=status,
                        professional_last_updated=timezone.now()
                    )
                
                numbers = request.POST.getlist('contact_number[]')
                types = request.POST.getlist('contact_type[]')
                for num, c_type in zip(numbers, types):
                    if num.strip():
                        ProfessionalContact.objects.create(
                            professional=prof,
                            contact_number=num,
                            contact_type=c_type,
                            contact_last_updated=timezone.now()
                        )
                        
                for a_inst_id, a_sched in zip(affil_inst_ids, affil_schedules):
                    if a_inst_id.strip():
                        affil_inst = Institution.objects.get(pk=a_inst_id)
                        Affiliation.objects.create(
                            professional=prof,
                            institution=affil_inst,
                            schedule=a_sched
                        )
                        
                messages.success(request, 'Professional saved successfully!')
                return redirect('referrals:manage')

            return JsonResponse({'success': False, 'message': 'Invalid form action provided.'})

        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Server Error: {str(e)}'})

    institutions = Institution.objects.prefetch_related('institutioncontact_set').order_by('institution_name')
    inst_search = (request.GET.get('inst_search') or '').strip()
    
    # Shared global region filter
    global_region = request.GET.get('region', 'All')
    
    inst_queryset = institutions
    if inst_search:
        inst_queryset = inst_queryset.filter(
            Q(institution_name__icontains=inst_search)
            | Q(institution_location__icontains=inst_search)
        )
        
    if global_region != 'All':
        places = REGION_MAP.get(global_region, [])
        if places:
            region_query = Q()
            for place in places:
                region_query |= Q(institution_location__icontains=place)
            inst_queryset = inst_queryset.filter(region_query).distinct()
            
    inst_page_obj, inst_querystring = paginate(request, inst_queryset, page_param='inst_page')

    professionals = Professional.objects.select_related('institution').prefetch_related(
        'professionalcontact_set', 'affiliation_set__institution'
    )
    professionals = _filter_professionals(
        professionals,
        request.GET.get('prof_search'),
        request.GET.get('prof_spec'),
        global_region # Apply the same region to professionals
    ).order_by('professional_name')
    prof_page_obj, prof_querystring = paginate(request, professionals, page_param='prof_page')

    return render(request, 'referrals/manage.html', {
        'institutions': institutions,
        'institution_list': inst_page_obj.object_list,
        'inst_page_obj': inst_page_obj,
        'inst_querystring': inst_querystring,
        'professionals': prof_page_obj.object_list,
        'prof_page_obj': prof_page_obj,
        'prof_querystring': prof_querystring,
        'current_inst_search': inst_search,
        'current_prof_search': request.GET.get('prof_search', ''),
        'current_prof_spec': request.GET.get('prof_spec', 'All'),
        'current_region': global_region,
        'specialization_choices': Professional.SpecializationChoices.choices,
        'contact_type_choices': ProfessionalContact.ContactTypeChoices.choices,
        'status_choices': Institution.StatusChoices.choices,
        'region_choices': REGION_CHOICES,
    })


def _professional_search_payload(professional):
    institution = professional.institution
    affiliations = [
        affiliation
        for affiliation in professional.affiliation_set.all()
        if affiliation.institution_id
    ]
    display_affiliation = next(
        (a for a in affiliations if a.institution_id == professional.institution_id),
        affiliations[0] if affiliations else None,
    )
    display_institution = institution or (
        display_affiliation.institution if display_affiliation else None
    )
    institution_name = (
        display_institution.institution_name if display_institution else ''
    )
    location = (
        (display_institution.institution_location or '').strip()
        if display_institution
        else ''
    )

    meta_parts = [professional.professional_specialization]
    if institution_name:
        meta_parts.append(institution_name)
    if location:
        meta_parts.append(location)

    label_parts = [professional.professional_name, *meta_parts]

    search_parts = [
        professional.professional_name,
        professional.professional_specialization or '',
    ]
    if institution_name:
        search_parts.append(institution_name)
    if location:
        search_parts.append(location)
    for affiliation in professional.affiliation_set.all():
        if not affiliation.institution_id:
            continue
        search_parts.append(affiliation.institution.institution_name or '')
        search_parts.append(affiliation.institution.institution_location or '')

    return {
        'id': professional.professional_id,
        'affiliation_id': (
            display_affiliation.affiliation_id if display_affiliation else ''
        ),
        'name': professional.professional_name,
        'specialization': professional.professional_specialization,
        'gender': professional.professional_gender or '',
        'institution': institution_name,
        'location': location,
        'meta': ' · '.join(meta_parts),
        'label': ' — '.join(label_parts),
        'search': ' '.join(part for part in search_parts if part).lower(),
    }


def professionals_api(request):
    if not request.session.get('user_id'):
        return JsonResponse({'results': []}, status=401)

    professionals = (
        Professional.objects.filter(
            professional_status=Professional.StatusChoices.ACTIVE
        )
        .select_related('institution')
        .prefetch_related('affiliation_set__institution')
    )
    professionals = _filter_professionals(
        professionals,
        request.GET.get('q'),
        request.GET.get('specialization'),
        request.GET.get('region')
    ).order_by('professional_name')

    return JsonResponse(
        {'results': [_professional_search_payload(item) for item in professionals]}
    )