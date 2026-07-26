from django.db import models
from apps.callers.models import CallSession


class Institution(models.Model):
    class StatusChoices(models.TextChoices):
            ACTIVE = 'Active', 'Active'
            INACTIVE = 'Inactive', 'Inactive'

    institution_id = models.AutoField(primary_key=True)
    institution_name = models.CharField(max_length=255)
    institution_location = models.CharField(max_length=255, blank=True, null=True)
    institution_status = models.CharField(max_length=50, 
                                    choices=StatusChoices.choices, 
                                    default=StatusChoices.ACTIVE)

    class Meta:
        db_table = 'institution'
   


class InstitutionContact(models.Model):
    class ContactTypeChoices(models.TextChoices):
        MOBILE = 'Mobile', 'Mobile'
        LANDLINE = 'Landline', 'Landline'
        EMAIL = 'Email', 'Email'

    institution_contact_id = models.AutoField(primary_key=True)
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE)
    institution_contact_number = models.CharField(max_length=50)
    institution_contact_type = models.CharField(max_length=50, choices=ContactTypeChoices.choices)
    institution_contact_last_update = models.DateTimeField()

    class Meta:
        db_table = 'institution_contact'


class Professional(models.Model):
    class SpecializationChoices(models.TextChoices):
        PSYCHIATRY = 'Psychiatry', 'Psychiatry'
        PSYCHOLOGY = 'Psychology', 'Psychology'

    class StatusChoices(models.TextChoices):
                ACTIVE = 'Active', 'Active'
                INACTIVE = 'Inactive', 'Inactive'

    professional_id = models.AutoField(primary_key=True)
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE)
    professional_gender = models.CharField(max_length=50, blank=True, null=True)
    professional_name = models.CharField(max_length=255)
    professional_specialization = models.CharField(max_length=50, choices=SpecializationChoices.choices)
    professional_last_updated = models.DateTimeField()
    professional_status = models.CharField(max_length=50, 
                                        choices=StatusChoices.choices, 
                                        default=StatusChoices.ACTIVE)
    
    class Meta:
        db_table = 'professional'


class ProfessionalContact(models.Model):
    class ContactTypeChoices(models.TextChoices):
        MOBILE = 'Mobile', 'Mobile'
        LANDLINE = 'Landline', 'Landline'
        EMAIL = 'Email', 'Email'

    contact_id = models.AutoField(primary_key=True)
    professional = models.ForeignKey(Professional, on_delete=models.CASCADE)
    contact_number = models.CharField(max_length=50)
    contact_type = models.CharField(max_length=50, choices=ContactTypeChoices.choices)
    contact_last_updated = models.DateTimeField()

    class Meta:
        db_table = 'professional_contact'


class Affiliation(models.Model):
    affiliation_id = models.AutoField(primary_key=True)
    professional = models.ForeignKey(Professional, on_delete=models.CASCADE)
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE)
    schedule = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'affiliation'


class SessionReferral(models.Model):
    session = models.OneToOneField(CallSession, primary_key=True, on_delete=models.CASCADE)
    professional = models.ForeignKey(Professional, on_delete=models.CASCADE)
    affiliation = models.ForeignKey(Affiliation, on_delete=models.CASCADE)

    class Meta:
        db_table = 'session_referral'