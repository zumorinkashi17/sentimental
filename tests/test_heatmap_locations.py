"""Tests for free-text location resolution and the PSGC sync command."""

from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.callers.models import Caller
from apps.heatmap.locations import normalize_location
from apps.heatmap.models import LocationAlias
from apps.heatmap.views import resolve_location
from tests.helpers import login, make_session, make_user


class NormalizeLocationTests(TestCase):
    def test_strips_prefixes_and_punctuation(self):
        self.assertEqual(normalize_location("Brgy. Lahug"), "lahug")
        self.assertEqual(normalize_location("I.T. Park"), "i t park")
        self.assertEqual(normalize_location("  Cebu & Mandaue "), "cebu and mandaue")
        self.assertEqual(normalize_location(None), "")


class ResolveLocationTests(TestCase):
    def test_static_alias_still_resolves(self):
        self.assertEqual(resolve_location("IT Park"), "Cebu City")
        self.assertEqual(resolve_location("IT Park, Cebu City"), "Cebu City")
        self.assertEqual(resolve_location("Mandaue"), "Mandaue City")

    def test_persisted_alias_resolves(self):
        LocationAlias.objects.create(
            raw_location="Binaliw",
            display_location="Binaliw",
            city="Cebu City",
            region_code="VII",
        )
        self.assertEqual(resolve_location("Binaliw"), "Cebu City")
        self.assertEqual(resolve_location("Binaliw, Cebu City"), "Cebu City")

    def test_unknown_and_ambiguous_inputs_return_none(self):
        self.assertIsNone(resolve_location("Unspecified"))
        self.assertIsNone(resolve_location("Nowhere Land"))


class SyncPhLocationsCommandTests(TestCase):
    REGIONS = [
        {"code": "070000000", "name": "Central Visayas", "regionName": "Region VII"},
    ]
    CITIES = [
        {"code": "073060000", "name": "City of Cebu", "regionCode": "070000000"},
        {"code": "073110000", "name": "City of Lapu-Lapu", "regionCode": "070000000"},
    ]
    BARANGAYS = [
        {"code": "073060001", "name": "Binaliw", "cityCode": "073060000", "regionCode": "070000000"},
        {"code": "073060002", "name": "Poblacion", "cityCode": "073060000", "regionCode": "070000000"},
        {"code": "073110001", "name": "Poblacion", "cityCode": "073110000", "regionCode": "070000000"},
        {"code": "073110002", "name": "Agus", "cityCode": "073110000", "regionCode": "070000000"},
    ]

    def _fake_get(self, url, **kwargs):
        class Response:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        if url.endswith("/regions/"):
            return Response(self.REGIONS)
        if url.endswith("/cities-municipalities/"):
            return Response(self.CITIES)
        if url.endswith("/barangays/"):
            return Response(self.BARANGAYS)
        raise AssertionError(f"unexpected URL: {url}")

    @patch("apps.heatmap.management.commands.sync_ph_locations.requests.get")
    def test_syncs_unique_names_and_skips_ambiguous(self, mock_get):
        mock_get.side_effect = self._fake_get

        call_command("sync_ph_locations", "--region", "VII")

        binaliw = LocationAlias.objects.get(raw_location="binaliw")
        self.assertEqual(binaliw.city, "Cebu City")
        self.assertEqual(binaliw.region_code, "VII")
        self.assertIsNotNone(binaliw.latitude)
        self.assertIsNotNone(binaliw.longitude)

        self.assertEqual(LocationAlias.objects.get(raw_location="agus").city, "Lapu-Lapu City")
        self.assertFalse(LocationAlias.objects.filter(raw_location="poblacion").exists())

        cebu_city = LocationAlias.objects.get(raw_location="city of cebu")
        self.assertEqual(cebu_city.city, "Cebu City")


class MapViewPersistedAliasTests(TestCase):
    def test_map_groups_a_new_place_under_its_city(self):
        LocationAlias.objects.create(
            raw_location="Binaliw",
            display_location="Binaliw",
            city="Cebu City",
            region_code="VII",
            latitude=10.3157,
            longitude=123.8854,
        )
        caller = Caller.objects.create(caller_name="Caller", caller_location="Binaliw")
        make_session(caller=caller)

        response = self.client.get(reverse("heatmap:map"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("Cebu City", response.context["hotspots_json"])
        self.assertIn("Region VII", response.context["summary_json"])

        response = self.client.get(reverse("heatmap:map"), {"region": "VII"})
        self.assertIn("Cebu City", response.context["summary_json"])


class HistoryFilterPersistedAliasTests(TestCase):
    def test_location_and_region_filters_match_a_new_place(self):
        LocationAlias.objects.create(
            raw_location="Binaliw",
            display_location="Binaliw",
            city="Cebu City",
            region_code="VII",
        )
        user = make_user()
        caller = Caller.objects.create(caller_name="Caller", caller_location="Binaliw")
        session = make_session(user=user, caller=caller)
        client = login(self.client, user)

        response = client.get(
            reverse("documentation:master_history"), {"location": "Cebu City"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, session.session_id)

        response = client.get(
            reverse("documentation:master_history"), {"region": "VII"}
        )
        self.assertContains(response, session.session_id)
