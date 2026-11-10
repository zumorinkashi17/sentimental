"""Seed ``LocationAlias`` from the free, key-less PSGC API.

Usage::

    python manage.py sync_ph_locations
    python manage.py sync_ph_locations --region VII
    python manage.py sync_ph_locations --region VII --region NCR
    python manage.py sync_ph_locations --flush

The command downloads the official Philippine Standard Geographic Code list
(regions -> cities/municipalities -> barangays) from
``https://psgc.gitlab.io/api`` and stores a mapping from each unique
barangay/city name to the canonical city key used by the heatmap. Names that
appear in more than one city (for example "Poblacion") are skipped because a
bare name cannot identify a single place.

Only places whose parent city already exists in ``LOCATION_COORDS`` are stored;
those are the cities the heatmap can plot. Landmarks such as "IT Park" are not
administrative names, so keep using ``LOCATION_ALIASES`` or add a row through
the Django admin for them.
"""

from __future__ import annotations

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.heatmap.locations import (
    PSGC_REGION_CODES,
    normalize_location,
    strip_city_prefix,
)
from apps.heatmap.models import LocationAlias
from apps.heatmap.views import CITY_REGION, LOCATION_ALIASES, LOCATION_COORDS, REGIONS

PSGC_API_BASE_URL = getattr(settings, "PSGC_API_BASE_URL", "https://psgc.gitlab.io/api")
REQUEST_TIMEOUT = 60


class Command(BaseCommand):
    help = "Sync barangay/city location aliases from the free PSGC API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--region",
            action="append",
            default=[],
            help="Limit to a heatmap region code (e.g. VII, NCR). Repeatable.",
        )
        parser.add_argument("--flush", action="store_true", help="Delete existing PSGC rows first.")
        parser.add_argument("--dry-run", action="store_true", help="Report without writing.")

    def handle(self, *args, **options):
        selected = set(options["region"])
        valid_codes = {code for code, _ in REGIONS if code != "all"}
        unknown = sorted(selected - valid_codes)
        if unknown:
            raise CommandError(f"unknown region code(s): {', '.join(unknown)}")

        try:
            regions = self._get("/regions/")
            cities = self._get("/cities-municipalities/")
            barangays = self._get("/barangays/")
        except (requests.RequestException, ValueError) as exc:
            raise CommandError(f"PSGC API request failed: {exc}") from exc

        region_by_psgc = {
            row.get("code", ""): PSGC_REGION_CODES.get(row.get("code", ""), "")
            for row in regions
        }
        static_lookup = self._static_lookup()

        # Build the full city index first so ambiguity is detected nationwide,
        # even when only one region is being written.
        city_by_code = {}
        city_aliases = []
        for row in cities:
            region_code = region_by_psgc.get(row.get("regionCode", ""), "")
            canonical = self._canonical_city(row.get("name", ""), region_code, static_lookup)
            if not canonical:
                continue
            city_by_code[row.get("code", "")] = (canonical, region_code)
            city_aliases.append((row.get("name", ""), canonical, region_code))

        candidates = {}
        for row in barangays:
            parent_code = row.get("cityCode") or row.get("municipalityCode")
            parent = city_by_code.get(parent_code)
            if not parent:
                continue
            name = row.get("name", "")
            key = normalize_location(name)
            if len(key) < 3:
                continue
            canonical, region_code = parent
            candidates.setdefault(key, set()).add((canonical, region_code, name))

        rows = {}
        ambiguous = 0
        for key, matches in candidates.items():
            if len(matches) > 1:
                ambiguous += 1
                continue
            canonical, region_code, original = next(iter(matches))
            if selected and region_code not in selected:
                continue
            rows[key] = self._row(key, original, canonical, region_code)

        for name, canonical, region_code in city_aliases:
            if selected and region_code not in selected:
                continue
            key = normalize_location(name)
            if len(key) < 3:
                continue
            rows.setdefault(key, self._row(key, name, canonical, region_code))

        if options["flush"]:
            if options["dry_run"]:
                count = LocationAlias.objects.filter(source=LocationAlias.Source.PSGC).count()
                self.stdout.write(f"Would delete {count} PSGC rows")
            else:
                deleted, _ = LocationAlias.objects.filter(source=LocationAlias.Source.PSGC).delete()
                self.stdout.write(f"Deleted {deleted} PSGC rows")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING(f"Dry run: would write {len(rows)} aliases"))
            self.stdout.write(f"  ambiguous barangay names skipped: {ambiguous}")
            return

        objects = [LocationAlias(**row) for row in rows.values()]
        with transaction.atomic():
            LocationAlias.objects.bulk_create(
                objects,
                update_conflicts=True,
                unique_fields=["raw_location"],
                update_fields=[
                    "display_location",
                    "city",
                    "region_code",
                    "latitude",
                    "longitude",
                    "source",
                    "updated_at",
                ],
            )

        self.stdout.write(self.style.SUCCESS(f"Wrote {len(objects)} aliases"))
        self.stdout.write(f"  ambiguous barangay names skipped: {ambiguous}")

    def _get(self, path):
        url = PSGC_API_BASE_URL.rstrip("/") + path
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _static_lookup():
        lookup = {}
        for city in LOCATION_COORDS:
            lookup.setdefault(normalize_location(city), city)
        for alias, city in LOCATION_ALIASES.items():
            lookup.setdefault(normalize_location(alias), city)
        return lookup

    @staticmethod
    def _canonical_city(name, region_code, static_lookup):
        stripped = strip_city_prefix(name)
        for candidate in (name, stripped, f"{stripped} City"):
            canonical = static_lookup.get(normalize_location(candidate))
            if not canonical:
                continue
            canonical_region = CITY_REGION.get(canonical)
            if canonical_region and region_code and canonical_region != region_code:
                continue
            return canonical
        return None

    @staticmethod
    def _row(key, original, canonical, region_code):
        coords = LOCATION_COORDS.get(canonical)
        return {
            "raw_location": key,
            "display_location": original,
            "city": canonical,
            "region_code": region_code or CITY_REGION.get(canonical, ""),
            "latitude": coords[0] if coords else None,
            "longitude": coords[1] if coords else None,
            "source": LocationAlias.Source.PSGC,
        }
