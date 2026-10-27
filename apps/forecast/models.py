"""Persisted forecast runs.

Monthly call-volume forecasts are stored rather than recomputed on every page
load, so the Dashboard, Call Volume Forecast and Shift Schedules pages all read
the *same* run. Nothing here touches historical ``call_session`` rows: a
``ForecastRun`` is an append-only artifact, and prior runs are never overwritten
(the only mutable field is the ``is_current`` pointer).

``residual_total_minus_shift_sum`` is a *forecast discrepancy* between the
independently forecast total and the sum of the three independently forecast
shifts. It is deliberately not distributed across shifts and is not an
"unallocated calls" figure.
"""

from django.db import models


# Kept in sync with apps.forecast.services.constants (ALL_SERIES / SERIES_LABELS).
SERIES_CHOICES = (
    ("total", "Total calls"),
    ("morning", "Morning shift"),
    ("afternoon", "Afternoon shift"),
    ("night", "Night shift"),
)

STATUS_COMPLETE = "complete"
STATUS_INVALID = "invalid"
STATUS_CHOICES = ((STATUS_COMPLETE, "Complete"), (STATUS_INVALID, "Invalid"))

RECONCILIATION_TOTAL_METHODS = (
    ("independent_total", "Independent total forecast"),
    ("sum_of_shifts", "Sum of the three shift forecasts"),
)

RECONCILIATION_SHIFT_METHODS = (
    ("raw", "Raw shift forecasts (unadjusted)"),
    ("proportional", "Proportionally scaled to the independent total"),
)


class ForecastRun(models.Model):
    """One generated forecast run (training window + config + evaluations)."""

    run_id = models.AutoField(primary_key=True)
    generated_at = models.DateTimeField()
    training_start = models.DateField()
    training_end = models.DateField()
    last_observed_month = models.DateField()
    horizon_months = models.PositiveIntegerField()

    prophet_version = models.CharField(max_length=32, blank=True, default="")
    model_config_name = models.CharField(max_length=32, blank=True, default="")
    yearly_seasonality = models.BooleanField(default=False)
    model_config = models.JSONField(default=dict, blank=True)

    reconciliation_total_method = models.CharField(
        max_length=32, choices=RECONCILIATION_TOTAL_METHODS, default="independent_total"
    )
    reconciliation_shift_method = models.CharField(
        max_length=32, choices=RECONCILIATION_SHIFT_METHODS, default="raw"
    )

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_COMPLETE)
    is_current = models.BooleanField(default=False, db_index=True)

    validation = models.JSONField(default=dict, blank=True)
    evaluation_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "forecast_run"
        indexes = [
            models.Index(fields=["is_current", "generated_at"], name="fr_current_gen_idx"),
            models.Index(fields=["training_end"], name="fr_training_end_idx"),
        ]

    def __str__(self) -> str:
        return (
            f"ForecastRun #{self.run_id} ({self.training_start:%Y-%m}..{self.training_end:%Y-%m}, "
            f"{self.model_config_name}, current={self.is_current})"
        )

    def make_current(self) -> None:
        """Mark this run as the one every page reads (clears other pointers)."""
        if self.is_current:
            return
        ForecastRun.objects.filter(is_current=True).exclude(pk=self.pk).update(is_current=False)
        self.is_current = True
        self.save(update_fields=["is_current"])


class ForecastRunMonth(models.Model):
    """One monthly point of one series within a run."""

    run = models.ForeignKey(ForecastRun, related_name="months", on_delete=models.CASCADE)
    month = models.DateField()
    series = models.CharField(max_length=16, choices=SERIES_CHOICES)

    yhat = models.FloatField()
    yhat_lower = models.FloatField(null=True, blank=True)
    yhat_upper = models.FloatField(null=True, blank=True)

    # Populated on 'total' rows only: total yhat - sum of the three shift yhats.
    residual_total_minus_shift_sum = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "forecast_run_month"
        unique_together = [("run", "month", "series")]
        indexes = [
            models.Index(fields=["series", "month"], name="frm_series_month_idx"),
            models.Index(fields=["month"], name="frm_month_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.series} {self.month:%Y-%m} = {self.yhat:.1f} (run {self.run_id})"
