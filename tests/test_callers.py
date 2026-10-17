"""Tests for callers app logic and transcribe behavior."""

from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.contrib.messages.storage.fallback import FallbackStorage

from apps.callers.models import CallSession, SESSION_ID_PREFIX
from apps.callers import transcription as tr
from apps.callers import views as cviews
from apps.callers.audio import AudioProcessingError
from tests.helpers import make_caller, make_session, make_shift, make_user, login


class SessionIdAllocationTests(TestCase):
    def test_next_session_preview_and_sequential_saves(self):
        s1 = make_session()
        self.assertTrue(s1.session_id.startswith(SESSION_ID_PREFIX))
        self.assertRegex(s1.session_id, r'^TPCB10-\d{4}$')
        self.assertEqual(s1.session_id, "TPCB10-0001")

        s2 = make_session()
        self.assertEqual(s2.session_id, "TPCB10-0002")

        self.assertEqual(CallSession.next_session_preview(), "TPCB10-0003")

    def test_next_number_handles_four_plus_digits(self):
        s = make_session()
        s.session_id = "TPCB10-9999"
        s.save()
        s2 = make_session()
        self.assertEqual(s2.session_id, "TPCB10-10000")
        self.assertEqual(CallSession.next_session_preview(), "TPCB10-10001")


class TranscriptionPayloadTests(TestCase):
    def test_build_prompt_and_parse_empty(self):
        self.assertIn("Caller", tr.build_prompt("Caller"))
        self.assertEqual(tr._parse_segments("", "Caller"), [])
        self.assertEqual(tr._parse_segments(None, "Caller"), [])

    def test_parse_segments_extracts_json_and_filters_blanks(self):
        raw = '```json\n[{"start": 0.1, "end": 1.0, "text": "Hello"}, {"start": 2.0, "end": 3.0, "text": ""}]\n```'
        segs = tr._parse_segments(raw, "Caller")
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["speaker"], "Caller")
        self.assertEqual(segs[0]["text"], "Hello")
        self.assertGreaterEqual(segs[0]["start"], 0.1)

    def test_parse_segments_accepts_bare_object(self):
        raw = '{"start": 1, "end": 2, "text": "Hi"}'
        segs = tr._parse_segments(raw, "Caller")
        self.assertEqual(len(segs), 1)

    def test_merge_segments_orders_by_time(self):
        caller = [{"speaker": "Caller", "start": 5, "end": 6, "text": "B"}]
        responder = [{"speaker": "Responder", "start": 0.5, "end": 1, "text": "A"}]
        merged = tr.merge_segments(caller, responder)
        self.assertEqual(merged[0]["text"], "A")
        self.assertEqual(merged[1]["text"], "B")

    def test_render_transcript_empty(self):
        self.assertIn("(no speech detected)", tr.render_transcript([]))


class TranscribeViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = login(self.client, self.user)

    def _mock_uploaded_files(self, mock_get):
        class F:
            name = "caller.webm"
            content_type = "audio/webm"
            def seek(self, n):
                pass
            def read(self):
                return b"abc"

        class FakeRequest:
            def __init__(self):
                self.FILES = {"caller": F(), "responder": F()}
                self.POST = {"caller_codec": "opus", "responder_codec": "opus"}
                self.session = {}
                self.method = "POST"

        def side_effect(key, default=None):
            return self.FILES.get(key) or self.POST.get(key) or default

        mock_get.side_effect = side_effect
        return FakeRequest()

    @patch("apps.callers.views.transcribe_tracks")
    @patch("apps.callers.views.normalize_track")
    def test_transcribe_audio_success_returns_json(self, mock_norm, mock_trans):
        class T:
            wav = b"wav"
            duration_ms = 500
            def as_levels(self):
                return {"rms": -20}

        mock_norm.return_value = T()
        mock_trans.return_value = ([], "transcript")
        url = reverse("callers:transcribe")
        from django.core.files.uploadedfile import SimpleUploadedFile

        resp = self.client.post(
            url,
            {
                "caller": SimpleUploadedFile("c.webm", b"a", content_type="audio/webm"),
                "responder": SimpleUploadedFile("r.webm", b"a", content_type="audio/webm"),
                "caller_codec": "opus",
                "responder_codec": "opus",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "success")

    def test_transcribe_audio_missing_files(self):
        url = reverse("callers:transcribe")
        resp = self.client.post(url, {})
        self.assertEqual(resp.status_code, 400)

    @patch("apps.callers.views.transcribe_tracks")
    @patch("apps.callers.views.normalize_track")
    def test_transcribe_audio_normalization_error_returns_400(self, mock_norm, mock_trans):
        from django.core.files.uploadedfile import SimpleUploadedFile

        mock_norm.side_effect = AudioProcessingError("boom")
        url = reverse("callers:transcribe")
        resp = self.client.post(
            url,
            {
                "caller": SimpleUploadedFile("c.webm", b"a", content_type="audio/webm"),
                "responder": SimpleUploadedFile("r.webm", b"a", content_type="audio/webm"),
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_transcribe_audio_missing_api_key_returns_500(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        url = reverse("callers:transcribe")
        with override_settings(GEMINI_API_KEY=""):
            resp = self.client.post(
                url,
                {
                    "caller": SimpleUploadedFile("c.webm", b"a", content_type="audio/webm"),
                    "responder": SimpleUploadedFile("r.webm", b"a", content_type="audio/webm"),
                },
            )
            self.assertEqual(resp.status_code, 500)


class CallersListFiltersTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = login(self.client, self.user)
        self.shift = make_shift()

    def test_list_filters_by_risk(self):
        c_high = make_caller(name="Alice")
        make_session(caller=c_high, shift=self.shift, risk="High")

        c_low = make_caller(name="Bob")
        make_session(caller=c_low, shift=self.shift, risk="Low")

        resp = self.client.get(reverse("callers:list") + "?risk=high")
        self.assertEqual(resp.status_code, 200)
        caller_list = resp.context["caller_list"]
        self.assertEqual(len(caller_list), 1)
        self.assertEqual(caller_list[0]["caller"].caller_name, "Alice")

    def test_list_search_by_name(self):
        make_session(caller=make_caller(name="Samantha"), shift=self.shift)
        make_session(caller=make_caller(name="John"), shift=self.shift)

        resp = self.client.get(reverse("callers:list") + "?search=sam")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["caller_list"]), 1)

    def test_list_search_by_caller_id(self):
        s = make_session(caller=make_caller(name="Zed"), shift=self.shift)
        caller_id = s.caller.caller_id
        resp = self.client.get(reverse("callers:list") + f"?search={caller_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["caller_list"]), 1)

    def test_list_period_today(self):
        from django.utils import timezone

        today = timezone.localdate()
        make_session(caller=make_caller(name="Today"), shift=self.shift, on=today)
        make_session(caller=make_caller(name="Old"), shift=self.shift, on=today - timedelta(days=5))

        resp = self.client.get(reverse("callers:list") + "?period=today")
        self.assertEqual(len(resp.context["caller_list"]), 1)
        self.assertEqual(resp.context["caller_list"][0]["caller"].caller_name, "Today")

    def test_database_view_renders(self):
        make_session(caller=make_caller(), shift=self.shift)
        resp = self.client.get(reverse("callers:database"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("caller_list", resp.context)
