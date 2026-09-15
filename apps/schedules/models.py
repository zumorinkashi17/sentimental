from django.db import models
from apps.accounts.models import User


class ShiftCatalog(models.Model):
    shift_id = models.AutoField(primary_key=True)
    shift_start_time = models.TimeField()
    shift_end_time = models.TimeField()

    class Meta:
        db_table = 'shift_catalog'


class ShiftSchedule(models.Model):
    schedule_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    shift = models.ForeignKey(ShiftCatalog, on_delete=models.CASCADE)
    shift_date = models.DateField(null=True, blank=True)
    schedule_status = models.CharField(max_length=50)

    class Meta:
        db_table = 'shift_schedule'