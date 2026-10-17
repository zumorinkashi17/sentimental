"""Guards the Phase 5 database indexes so they cannot silently disappear."""

from django.test import SimpleTestCase

from apps.accounts.models import DayOffRequest, User
from apps.callers.models import CallSession
from apps.reports.models import Report
from apps.referrals.models import Institution, Professional
from apps.schedules.models import ShiftSchedule

EXPECTED_INDEXES = {
    User: {"user_role_status_idx": ["user_role", "user_status"]},
    DayOffRequest: {"dor_status_date_idx": ["requested_status", "requested_date"]},
    CallSession: {
        "cs_date_time_idx": ["session_call_date", "session_time_called"],
        "cs_user_dt_idx": ["user", "session_call_date", "session_time_called"],
        "cs_caller_dt_idx": ["caller", "session_call_date", "session_time_called"],
    },
    ShiftSchedule: {
        "ss_date_status_idx": ["shift_date", "schedule_status"],
        "ss_user_date_idx": ["user", "shift_date"],
    },
    Institution: {"inst_status_idx": ["institution_status"]},
    Professional: {
        "prof_status_idx": ["professional_status"],
        "prof_spec_idx": ["professional_specialization"],
    },
    Report: {"report_date_idx": ["report_generated_date"]},
}


class IndexMetadataTests(SimpleTestCase):
    def test_expected_indexes_are_declared(self):
        for model, expected in EXPECTED_INDEXES.items():
            declared = {index.name: list(index.fields) for index in model._meta.indexes}
            for name, fields in expected.items():
                with self.subTest(model=model.__name__, index=name):
                    self.assertIn(name, declared)
                    self.assertEqual(declared[name], fields)
