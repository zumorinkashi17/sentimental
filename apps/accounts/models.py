from django.db import models
from django.contrib.auth.hashers import make_password
from django.contrib.auth.hashers import check_password as django_check_password

class User(models.Model):
    class RoleChoices(models.TextChoices):
        ADMIN = 'Admin', 'Admin'
        RESPONDER = 'Responder', 'Responder'

    class StatusChoices(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    user_id = models.AutoField(primary_key=True)
    user_first_name = models.CharField(max_length=255)
    user_last_name = models.CharField(max_length=255)
    user_email = models.EmailField(max_length=255, unique=True)
    user_number = models.CharField(max_length=50, blank=True, null=True)
    user_password = models.CharField(max_length=255, null=True, blank=True)  
    user_image = models.CharField(max_length=255, null=True, blank=True)  
    user_setup_token = models.CharField(max_length=100, blank=True, null=True)

    def set_password(self, raw_password):
        self.user_password = make_password(raw_password)

    def check_password(self, raw_password):
        return django_check_password(raw_password, self.user_password)

    user_role = models.CharField(max_length=50, choices=RoleChoices.choices)
    user_location = models.CharField(max_length=255, blank=True, null=True)
    user_status = models.CharField(max_length=50, 
                                    choices=StatusChoices.choices, 
                                    default=StatusChoices.ACTIVE)

    class Meta:
        db_table = 'user'

    def __str__(self):
        return f"{self.user_first_name} {self.user_last_name}"


class UserLog(models.Model):
    log_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    log_token = models.CharField(max_length=255)
    log_time_in = models.DateTimeField(auto_now_add=True)
    log_time_out = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'user_log'


class DayOffRequest(models.Model):
    class StatusChoices(models.TextChoices):
        PENDING = 'Pending', 'Pending'
        APPROVED = 'Approved', 'Approved'
        DENIED = 'Denied', 'Denied'

    request_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='dayoffrequest_user_set')
    requested_date = models.DateField()
    requested_reason = models.CharField(max_length=255)
    requested_additional_notes = models.TextField(blank=True, null=True)
    requested_status = models.CharField(
        max_length=50, 
        choices=StatusChoices.choices, 
        default=StatusChoices.PENDING
    )
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        db_column='processed_by',
        related_name='dayoffrequest_processed_by_set',
        blank=True,
        null=True,
    )

    class Meta:
        db_table = 'day_off_request'