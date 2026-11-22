"""Unit and integration tests for C-SSRS suicide risk flagging.

Covers the exact criteria in the specification: direct high-risk Bisaya /
Taglish statements, preparatory acts and method/plan phrasing, spelling
variants, moderate ideation, negation and idiom false positives, plus
persistence through the save-session endpoint.
"""

import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.callers.models import CallSession
from apps.callers.nlp.risk import SuicideRiskEvaluator, evaluate_suicide_risk
from tests.helpers import login, make_professional, make_shift, make_user


class DirectHighRiskTests(SimpleTestCase):
    def setUp(self):
        self.evaluator = SuicideRiskEvaluator()

    def assert_high(self, text):
        result = self.evaluator.evaluate(text)
        self.assertEqual(result["risk_level"], "HIGH_RISK", msg=result)
        self.assertTrue(result["matched_phrases"], msg=result)
        self.assertTrue(result["cssrs_category"], msg=result)
        return result

    def test_bisaya_direct_wish_to_die(self):
        result = self.assert_high("nahan nako mamatay")
        self.assertEqual(result["risk_level"], "HIGH_RISK")

    def test_bisaya_plan_to_end_life(self):
        self.assert_high("ga plano ko e end ako kinabuhi")

    def test_bisaya_magpakamatay_and_maghikog(self):
        self.assert_high("magpakamatay")
        self.assert_high("maghikog")

    def test_taglish_direct_statement(self):
        self.assert_high("Gusto ko magpakamatay")


class BehaviorAndMethodTests(SimpleTestCase):
    def setUp(self):
        self.evaluator = SuicideRiskEvaluator()

    def test_goodbye_note_is_high_risk_preparatory_act(self):
        result = self.evaluator.evaluate("I wrote a goodbye note to my family")
        self.assertEqual(result["risk_level"], "HIGH_RISK")
        self.assertIn("Preparatory", result["cssrs_category"])

    def test_giving_things_away_is_high_risk_preparatory_act(self):
        result = self.evaluator.evaluate("She gave away all her things yesterday")
        self.assertEqual(result["risk_level"], "HIGH_RISK")

    def test_actual_attempt_is_high_risk(self):
        result = self.evaluator.evaluate("I tried to kill myself last night")
        self.assertEqual(result["risk_level"], "HIGH_RISK")
        self.assertTrue(any("Attempt" in c for c in result["cssrs_category"].split("; ")))

    def test_plan_and_intent_is_high_risk(self):
        result = self.evaluator.evaluate(
            "I have a specific plan and I intend to do it tonight"
        )
        self.assertEqual(result["risk_level"], "HIGH_RISK")

    def test_method_phrases_are_high_risk(self):
        for text in ("I will hang myself with a rope", "I plan to take an overdose"):
            with self.subTest(text=text):
                self.assertEqual(
                    self.evaluator.evaluate(text)["risk_level"], "HIGH_RISK"
                )

    def test_cebuano_ingestion_method_is_high_risk(self):
        result = self.evaluator.evaluate(
            "Nakahunahuna ko nga moinom og daghang tambal para makatulog ug di na momata."
        )
        self.assertEqual(result["risk_level"], "HIGH_RISK")
        self.assertIn("Ingestion", result["cssrs_category"])

    def test_sample_conversation_caller_method_is_high_risk(self):
        text = (
            "Responder:\n"
            "Nakahunahuna ba ka og buhaton nga makapasakit sa imong kaugalingon?\n\n"
            "Caller:\n"
            "Nakahunahuna ko nga molayas na lang miss... or moinom og daghang tambal "
            "para makatulog ug di na momata kay di ko gusto maka-dungog sa kasaba. "
            "Pero nahadlok man pud ko buhaton."
        )
        result = self.evaluator.evaluate(text)
        self.assertEqual(result["risk_level"], "HIGH_RISK")
        self.assertIn("Ingestion", result["cssrs_category"])


class SpellingVariantTests(SimpleTestCase):
    def setUp(self):
        self.evaluator = SuicideRiskEvaluator()

    def test_ganahan_variant(self):
        self.assertEqual(
            self.evaluator.evaluate("ganahan nako mamatay")["risk_level"], "HIGH_RISK"
        )

    def test_i_end_akong_kinabuhi_variant(self):
        self.assertEqual(
            self.evaluator.evaluate("plano ko i-end akong kinabuhi")["risk_level"],
            "HIGH_RISK",
        )

    def test_casing_and_extra_whitespace(self):
        self.assertEqual(
            self.evaluator.evaluate("  NAHAN   NAKO   MAMATAY  ")["risk_level"],
            "HIGH_RISK",
        )

    def test_huna_huna_spelling_variant(self):
        self.assertEqual(
            self.evaluator.evaluate("naa koy huna-huna nga magpakamatay")["risk_level"],
            "HIGH_RISK",
        )


class ModerateRiskTests(SimpleTestCase):
    def setUp(self):
        self.evaluator = SuicideRiskEvaluator()

    def test_kapoy_na_kaayo_mabuhi_is_moderate(self):
        result = self.evaluator.evaluate("kapoy na kaayo mabuhi")
        self.assertEqual(result["risk_level"], "MODERATE_RISK")
        self.assertIn("Wish to be Dead", result["cssrs_category"])

    def test_sana_di_nako_kamata_is_moderate(self):
        result = self.evaluator.evaluate("sana di nako kamata")
        self.assertEqual(result["risk_level"], "MODERATE_RISK")

    def test_dili_na_gyud_nako_kaya_is_distress_not_risk(self):
        result = self.evaluator.evaluate("Dili na gyud nako kaya.")
        self.assertEqual(result["risk_level"], "LOW")
        self.assertEqual(result["cssrs_category"], "No Risk Indicators")

    def test_non_specific_suicidal_thoughts_is_moderate(self):
        result = self.evaluator.evaluate("I have thoughts of suicide")
        self.assertEqual(result["risk_level"], "MODERATE_RISK")
        self.assertIn("Non-Specific", result["cssrs_category"])


class NegationAndIdiomTests(SimpleTestCase):
    def setUp(self):
        self.evaluator = SuicideRiskEvaluator()

    def test_negated_bisaya_phrase_is_low(self):
        result = self.evaluator.evaluate("dili ko ganahan mamatay")
        self.assertEqual(result["risk_level"], "LOW")
        self.assertTrue(result["matched_phrases"])

    def test_negated_plan_is_low(self):
        result = self.evaluator.evaluate("wala ko nagplano magpakamatay")
        self.assertEqual(result["risk_level"], "LOW")

    def test_idiom_die_of_laughter_is_low(self):
        result = self.evaluator.evaluate("mamatay ko sa katawa")
        self.assertEqual(result["risk_level"], "LOW")
        self.assertIn("Idiom", result["cssrs_category"])

    def test_idiom_patay_sa_gutom_is_low(self):
        self.assertEqual(
            self.evaluator.evaluate("patay sa gutom")["risk_level"], "LOW"
        )

    def test_unrelated_text_is_low(self):
        result = self.evaluator.evaluate("Maayong buntag, unsay kahimtang karon?")
        self.assertEqual(result["risk_level"], "LOW")

    def test_generic_huna_huna_is_not_a_risk_indicator(self):
        result = self.evaluator.evaluate("huna huna")
        self.assertEqual(result["risk_level"], "LOW")
        self.assertEqual(result["matched_phrases"], [])

    def test_wala_nakoy_ihatag_is_not_a_risk_indicator(self):
        result = self.evaluator.evaluate("Wala nakoy ihatag.")
        self.assertEqual(result["risk_level"], "LOW")
        self.assertEqual(result["matched_phrases"], [])

    def test_clear_denial_is_low(self):
        result = self.evaluator.evaluate(
            "Dili, sir. Wala gyud ko naghunahuna ana."
        )
        self.assertEqual(result["risk_level"], "LOW")
        self.assertEqual(
            result["cssrs_category"], "Explicit Denial of Suicidal Ideation"
        )

    def test_clear_denial_does_not_override_real_risk(self):
        result = self.evaluator.evaluate(
            "Wala gyud ko naghunahuna ana. Pero karon, tinuod gayud, "
            "nahan nako mamatay."
        )
        self.assertEqual(result["risk_level"], "HIGH_RISK")

    def test_responder_risk_question_is_ignored(self):
        text = (
            "[Responder] ni-abot ba sa imong huna-huna nga pasakitan ang imong "
            "kaugalingon o tapuson ang imong kinabuhi?\n"
            "[Caller] Gusto lang ko og break, sir."
        )
        result = self.evaluator.evaluate(text)
        self.assertEqual(result["risk_level"], "LOW")
        self.assertNotIn("huna huna", result["matched_phrases"])

    def test_block_responder_speech_is_ignored(self):
        text = (
            "Responder:\n"
            "Nagplano ba ka magpakamatay?\n\n"
            "[PHASE 6 – RISK ASSESSMENT]\n\n"
            "Caller:\n"
            "Gusto lang ko og tubig, sir."
        )
        result = self.evaluator.evaluate(text)
        self.assertEqual(result["risk_level"], "LOW")
        self.assertNotIn("magpakamatay", result["matched_phrases"])

    def test_burnout_caller_denial_with_distress_is_low(self):
        text = (
            "Counselor:\n"
            "Ni-abot ba sa imong huna-huna nga pasakitan ang imong kaugalingon?\n\n"
            "Caller:\n"
            "Wala man sir. Hadlok ko anang pasakitan ang kaugalingon kay nakita nako "
            "sa ER unsa na kalisod ang agian sa mga pasyente. Gusto lang ko og break, "
            "sir. Dili na gyud nako kaya."
        )
        result = self.evaluator.evaluate(text)
        self.assertEqual(result["risk_level"], "LOW")
        self.assertIn("Denial", result["cssrs_category"])

    def test_sample_caller_denial_is_low(self):
        text = (
            "[Responder] ni-abot ba sa imong huna-huna nga pasakitan ang imong "
            "kaugalingon o tapuson ang imong kinabuhi?\n"
            "[Caller] Wala man sir. Hadlok ko anang pasakitan ang kaugalingon "
            "kay nakita nako sa ER unsa na kalisod ang agian sa mga pasyente."
        )
        result = self.evaluator.evaluate(text)
        self.assertEqual(result["risk_level"], "LOW")
        self.assertIn("Denial", result["cssrs_category"])


class StructuredOutputTests(SimpleTestCase):
    def test_output_keys(self):
        result = evaluate_suicide_risk("nahan nako mamatay")
        for key in ("risk_level", "cssrs_category", "matched_phrases", "flag_reason"):
            self.assertIn(key, result)
        self.assertIsInstance(result["matched_phrases"], list)

    def test_review_level_is_never_returned(self):
        for text in (
            "nahan nako mamatay",
            "kapoy na mabuhi",
            "dili ko ganahan mamatay",
            "wala ko nagplano magpakamatay",
        ):
            with self.subTest(text=text):
                self.assertNotEqual(
                    evaluate_suicide_risk(text)["risk_level"], "REVIEW"
                )

    def test_rules_are_editable_without_code_changes(self):
        import tempfile
        from pathlib import Path

        rules = {
            "settings": {"negation_window": 5, "severity_weights": {"HIGH_RISK": 100}},
            "normalization": {"repeated_char_max": 2, "variants": []},
            "idioms": [],
            "negations": [],
            "tiers": {
                "HIGH_RISK": [{"category": "Custom", "phrases": ["custom trigger"]}],
                "MODERATE_RISK": [],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rules.json"
            path.write_text(json.dumps(rules), encoding="utf-8")
            evaluator = SuicideRiskEvaluator(str(path))
            result = evaluator.evaluate("custom trigger detected")
            self.assertEqual(result["risk_level"], "HIGH_RISK")
            self.assertEqual(result["cssrs_category"], "Custom")


class AnalysisEndpointRiskTests(TestCase):
    def setUp(self):
        self.client = login(self.client, make_user())

    def test_analyze_returns_suicide_risk_payload(self):
        response = self.client.post(
            reverse("callers:analyze"),
            data=json.dumps({"text": "nahan nako mamatay"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("suicide_risk", payload)
        self.assertEqual(payload["suicide_risk"]["risk_level"], "HIGH_RISK")


class SaveSessionRiskPersistenceTests(TestCase):
    def setUp(self):
        self.client = login(self.client, make_user())
        self.shift = make_shift()

    def payload(self, **overrides):
        payload = {
            "callDate": "January 15, 2026",
            "timeCalled": "09:00 AM",
            "timeEnded": "09:30 AM",
            "callShift": self.shift.pk,
            "callerName": "Ana",
            "riskAssessment": "Low",
            "aiSummary": "Caller shared her situation.",
            "rawTranscript": "",
        }
        payload.update(overrides)
        return payload

    def post(self, **overrides):
        return self.client.post(
            reverse("callers:save_session"),
            data=json.dumps(self.payload(**overrides)),
            content_type="application/json",
        )

    def test_high_risk_transcript_is_persisted(self):
        response = self.post(rawTranscript="Caller: nahan nako mamatay")
        self.assertEqual(response.status_code, 200)
        session = CallSession.objects.get()
        self.assertEqual(session.session_risk_assessment, "High Risk")
        payload = response.json()
        self.assertEqual(payload["suicide_risk"]["risk_level"], "HIGH_RISK")
        self.assertEqual(payload["suicide_risk"]["risk_assessment"], "High Risk")

    def test_preparatory_note_is_persisted_as_high_risk(self):
        self.post(additionalComments="He wrote a goodbye note before calling.")
        session = CallSession.objects.get()
        self.assertEqual(session.session_risk_assessment, "High Risk")

    def test_negated_text_keeps_submitted_risk_assessment(self):
        response = self.post(rawTranscript="dili ko ganahan mamatay")
        session = CallSession.objects.get()
        self.assertEqual(session.session_risk_assessment, "Low")
        self.assertEqual(response.json()["suicide_risk"]["risk_level"], "LOW")

    def test_plain_text_keeps_submitted_risk_assessment(self):
        response = self.post(rawTranscript="Caller asked about shelter services.")
        session = CallSession.objects.get()
        self.assertEqual(session.session_risk_assessment, "Low")
        self.assertEqual(response.json()["suicide_risk"]["risk_level"], "LOW")

    def test_manual_script_notes_are_now_evaluated(self):
        self.post(manualScriptNotes="ga plano ko e end ako kinabuhi")
        session = CallSession.objects.get()
        self.assertEqual(session.session_risk_assessment, "High Risk")


class RiskTrainingTests(SimpleTestCase):
    def test_train_risk_builds_a_model(self):
        from apps.callers.nlp.train_risk import DEFAULT_ANNOTATIONS, train

        with tempfile.TemporaryDirectory() as tmp:
            summary = train(DEFAULT_ANNOTATIONS, Path(tmp) / "risk", epochs=1)

        self.assertEqual(summary["labels"], ["LOW", "MODERATE_RISK", "HIGH_RISK"])
        self.assertGreater(summary["records"], 0)
        self.assertIn("accuracy", summary["best_metrics"])
