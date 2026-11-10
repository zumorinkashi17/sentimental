from django.db import models

from apps.heatmap.locations import normalize_location


class LocationAlias(models.Model):
    """Persisted mapping from a free-text caller location to a canonical city.

    Rows are written by the ``sync_ph_locations`` command (which reads the free
    PSGC API) or by staff through the Django admin, so a brand-new barangay or
    landmark can be categorised without a code change. ``raw_location`` stores
    the normalised key that ``resolve_location`` looks up.
    """

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        PSGC = "psgc", "PSGC"

    raw_location = models.CharField(max_length=255, unique=True)
    display_location = models.CharField(max_length=255, blank=True, default="")
    city = models.CharField(max_length=255)
    region_code = models.CharField(max_length=16, blank=True, default="")
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "location_alias"
        verbose_name_plural = "location aliases"
        indexes = [
            models.Index(fields=["city"], name="la_city_idx"),
            models.Index(fields=["region_code"], name="la_region_idx"),
        ]

    def __str__(self):
        return f"{self.display_location or self.raw_location} -> {self.city}"

    def save(self, *args, **kwargs):
        self.raw_location = normalize_location(self.raw_location)
        if not self.display_location:
            self.display_location = self.raw_location
        super().save(*args, **kwargs)
