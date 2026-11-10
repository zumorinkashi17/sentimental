from django.test import TestCase
from django.urls import reverse

from tests.helpers import login, make_institution, make_professional, make_user


class ProfessionalsApiTests(TestCase):
    def setUp(self):
        self.client = login(self.client, make_user())
        self.institution = make_institution(
            name="Vicente Sotto Medical Center", location="Cebu City"
        )
        self.professional = make_professional(
            institution=self.institution,
            name="Dr. Maria Reyes",
            specialization="Psychiatry",
        )

    def _results(self, **params):
        response = self.client.get(reverse("referrals:professionals_api"), params)
        self.assertEqual(response.status_code, 200)
        return response.json()["results"]

    def test_search_by_professional_name(self):
        results = self._results(q="reyes")

        self.assertEqual(
            [row["id"] for row in results],
            [self.professional.professional_id],
        )

    def test_search_by_institution(self):
        results = self._results(q="sotto")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Dr. Maria Reyes")

    def test_search_by_location(self):
        results = self._results(q="cebu")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["location"], "Cebu City")

    def test_excludes_inactive_professionals(self):
        make_professional(
            institution=self.institution,
            name="Dr. Inactive",
            status="Inactive",
        )

        names = [row["name"] for row in self._results(q="")]

        self.assertIn("Dr. Maria Reyes", names)
        self.assertNotIn("Dr. Inactive", names)

    def test_requires_login(self):
        self.client.logout()

        response = self.client.get(reverse("referrals:professionals_api"))

        self.assertEqual(response.status_code, 401)
