from django.contrib import admin

from apps.heatmap.models import LocationAlias


@admin.register(LocationAlias)
class LocationAliasAdmin(admin.ModelAdmin):
    list_display = ("display_location", "city", "region_code", "source", "updated_at")
    list_filter = ("source", "region_code")
    search_fields = ("raw_location", "display_location", "city")
    ordering = ("city", "raw_location")
    readonly_fields = ("created_at", "updated_at")
