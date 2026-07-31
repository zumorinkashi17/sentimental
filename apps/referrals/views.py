from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.utils import timezone
from django.contrib import messages
from .models import (
    Institution, InstitutionContact, Professional, ProfessionalContact, Affiliation
)

def directory_view(request):
    # 1. Check if the user is logged in at all
    if not request.session.get('user_id'):
        messages.error(request, "You must be logged in to view the directory.")
        return redirect('accounts:login')

    professionals = Professional.objects.filter(
        professional_status=Professional.StatusChoices.ACTIVE
    ).select_related('institution').prefetch_related(
        'professionalcontact_set', 'affiliation_set__institution'
    )
    
    return render(request, 'referrals/directory.html', {
        'professionals': professionals,
        'specialization_choices': Professional.SpecializationChoices.choices,
    })

def manage_view(request):
    # 1. Check if the user is logged in
    if not request.session.get('user_id'):
        messages.error(request, "You must be logged in to access this page.")
        return redirect('accounts:login')
        
    # 2. Restrict access to Admins only
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
                
                # Duplicate check logic
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
                primary_inst_id = request.POST.get('institution_id')
                status = request.POST.get('professional_status') or Professional.StatusChoices.ACTIVE
                
                # --- PROFESSIONAL DUPLICATE PREVENTION ---
                duplicate_prof_query = Professional.objects.filter(
                    professional_name__iexact=name,
                    professional_specialization=specialization
                )
                if prof_id:
                    duplicate_prof_query = duplicate_prof_query.exclude(pk=prof_id)
                
                if duplicate_prof_query.exists():
                    messages.error(request, f'A professional named "{name}" with this specialization already exists.')
                    return redirect('referrals:manage')
                # -----------------------------------------

                # --- DUPLICATE AFFILIATIONS CHECK ---
                affil_inst_ids = request.POST.getlist('affiliation_inst_id[]')
                affil_schedules = request.POST.getlist('affiliation_schedule[]')
                
                # Filter out empty strings to only check actual selected affiliations
                valid_affil_ids = [aid for aid in affil_inst_ids if aid.strip()]
                
                if len(valid_affil_ids) != len(set(valid_affil_ids)):
                    messages.error(request, 'You cannot add the same institution multiple times in the affiliations list.')
                    return redirect('referrals:manage')
                # ------------------------------------

                primary_institution = Institution.objects.get(pk=primary_inst_id) if primary_inst_id else None

                if prof_id:
                    prof = Professional.objects.get(pk=prof_id)
                    prof.professional_name = name
                    prof.professional_gender = gender
                    prof.professional_specialization = specialization
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

    institutions = Institution.objects.prefetch_related('institutioncontact_set').all()
    professionals = Professional.objects.select_related('institution').prefetch_related(
        'professionalcontact_set', 'affiliation_set__institution'
    ).all()

    return render(request, 'referrals/manage.html', {
        'institutions': institutions,
        'professionals': professionals,
        'specialization_choices': Professional.SpecializationChoices.choices,
        'contact_type_choices': ProfessionalContact.ContactTypeChoices.choices,
        'status_choices': Institution.StatusChoices.choices,
    })