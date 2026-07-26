from django.db import models
from apps.accounts.models import User


class Report(models.Model):
    class ReportTypeChoices(models.TextChoices):
        COMPLIANCE = 'Compliance', 'Compliance'
        ANALYTICS = 'Analytics', 'Analytics'
        SECURITY = 'Security', 'Security'

    report_id = models.AutoField(primary_key=True)
    report_title = models.CharField(max_length=255)
    report_generated_date = models.DateField()
    report_type = models.CharField(max_length=100, choices=ReportTypeChoices.choices)
    generated_by = models.ForeignKey(User, on_delete=models.CASCADE, db_column='generated_by')

    class Meta:
        db_table = 'report'
        