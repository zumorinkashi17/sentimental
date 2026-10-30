import json
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse

from .nlp import analyze
from .nlp.summary import build_summary
from .nlp.textrank import summarize


class RuleExtractionTests(SimpleTestCase):
    def test_extracts_caller_fields_from_english_transcript(self):
        text = (
            "[CALLER] Hi, my name is Maria Santos. I am 22 years old, female, "
            "single, and I live in Mandaue City. I called because my partner "
            "and I keep fighting."
        )

        result = analyze(text)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["fields"]["callerName"], "Maria Santos")
        self.assertEqual(result["fields"]["callerAge"], 22)
        self.assertEqual(result["fields"]["callerGender"], "Female")
        self.assertEqual(result["fields"]["callerStatus"], "Single")
        self.assertEqual(result["fields"]["callerLocation"], "Mandaue City")

    def test_extracts_bisaya_fields(self):
        text = (
            "[CALLER] Ako si Juan Dela Cruz, 30 anyos, lalaki, minyo, "
            "taga Cebu City. Naningkamot ko og tawag kay nag-away mi sa akong asawa."
        )

        result = analyze(text)

        self.assertEqual(result["fields"]["callerName"], "Juan Dela Cruz")
        self.assertEqual(result["fields"]["callerAge"], 30)
        self.assertEqual(result["fields"]["callerGender"], "Male")
        self.assertEqual(result["fields"]["callerStatus"], "Married")
        self.assertEqual(result["fields"]["callerLocation"], "Cebu City")

    def test_generates_summary(self):
        text = (
            "The caller said she had an argument with her partner last night. "
            "She felt unsafe and could not sleep. She has been crying all day. "
            "The responder validated her feelings and discussed breathing exercises. "
            "They agreed on a follow-up call tomorrow."
        )

        result = analyze(text)

        self.assertTrue(result["summary"])
        self.assertGreater(len(result["summary"]), 20)

    def test_risk_and_reason_are_not_auto_filled(self):
        result = analyze("My name is Ana. I am 25 years old.")

        self.assertNotIn("riskLevel", result["fields"])
        self.assertNotIn("reasonForCalling", result["fields"])

    def test_prefers_caller_turns_and_defaults_missing_fields(self):
        text = (
            "[PHASE 1 - OPENING]\n\n"
            "Responder:\n"
            "Maayong gabii. Ako si Diane. Unsa akong matabang?\n\n"
            "Caller:\n"
            "Rey akong pangalan, miss. Nagsugod ra ni, gisuwayan nako. "
            "Naa ko sa Danao City ron.\n"
        )

        result = analyze(text)

        self.assertEqual(result["fields"]["callerName"], "Rey")
        self.assertEqual(result["fields"]["callerAge"], "N/A")
        self.assertEqual(result["fields"]["callerGender"], "N/A")
        self.assertEqual(result["fields"]["callerStatus"], "N/A")
        self.assertEqual(result["fields"]["callerLocation"], "Danao City")

    def test_auto_fills_responder_intervention(self):
        text = (
            "Responder:\n"
            "Maayong gabii. Ako si Diane. Unsa akong matabang?\n\n"
            "Caller:\n"
            "Rey akong pangalan. Naa ko sa Danao City.\n\n"
            "Responder:\n"
            "Kana nga mga kurog ug singot, gitawag na og withdrawal symptoms.\n"
            "Inhale og lalom sa imong ilong... pugngi kadiyot... ug exhale sa baba.\n"
            "Mas maayo nga mo-consult ka og doctor. "
            "Naa tay DOH Treatment and Rehabilitation Center sa Mandaue.\n"
        )

        result = analyze(text)

        self.assertEqual(result["fields"]["intervention"], "- Given Referrals")
        self.assertEqual(
            result["field_meta"]["intervention"]["categories"],
            ["Given Referrals"],
        )

    def test_classifies_refused_referral_from_caller_turn(self):
        text = (
            "Caller:\n"
            "Dili lang sa ko muadto nila. Dili pa ko ready.\n\n"
            "Responder:\n"
            "Sige.\n"
        )

        result = analyze(text)

        self.assertEqual(
            result["field_meta"]["intervention"]["categories"],
            ["Refused Referrals"],
        )

    def test_auto_fills_multiple_intervention_labels(self):
        text = (
            "Responder:\n"
            "Kana nga mga kurog ug singot, gitawag na og withdrawal symptoms.\n"
            "Nag-react ang imong lawas kay naanad siya sa alcohol. "
            "Ang severe withdrawal makadaot sa lawas.\n"
            "Mas maayo nga mo-consult ka og doctor. "
            "Naa tay DOH Treatment and Rehabilitation Center sa Mandaue.\n"
        )

        result = analyze(text)

        self.assertEqual(
            result["fields"]["intervention"],
            "- Given Referrals\n- Psychoeducation",
        )
        self.assertEqual(
            result["field_meta"]["intervention"]["categories"],
            ["Given Referrals", "Psychoeducation"],
        )

    def test_extracts_name_followed_by_title(self):
        result = analyze("Caller:\nMarco lang sir. 31 na ko sir.\n")

        self.assertEqual(result["fields"]["callerName"], "Marco")
        self.assertEqual(result["fields"]["callerAge"], 31)

    def test_ignores_emotional_words_as_names_and_offices_as_locations(self):
        text = (
            "Responder:\n"
            "Unsa may itawag nako nimo?\n\n"
            "Caller:\n"
            "Jay na lang ma'am.\n\n"
            "Responder:\n"
            "Hi Jay. Pila na may imong edad?\n\n"
            "Caller:\n"
            "21 ko ma'am. (Deep breathing) ...Sakit lang gyud ma'am kay ni-asa na mi ato.\n\n"
            "Responder:\n"
            "Naa ba moy guidance counselor o Student Affairs office sa inyong school?\n\n"
            "Caller:\n"
            "Suwayan nako'g adto ugma sa Student Affairs.\n"
        )

        result = analyze(text)

        self.assertEqual(result["fields"]["callerName"], "Jay")
        self.assertEqual(result["fields"]["callerAge"], 21)
        self.assertEqual(result["fields"]["callerLocation"], "N/A")
        self.assertEqual(
            result["fields"]["intervention"],
            "- Referred to Guidance Counselors",
        )

    def test_infers_gender_from_spouse_reference(self):
        text = (
            "Caller:\nAko si Liza. 45 na ko. "
            "Nagbulag mi sa akong bana ten years ago na.\n"
        )

        result = analyze(text)

        self.assertEqual(result["fields"]["callerName"], "Liza")
        self.assertEqual(result["fields"]["callerAge"], 45)
        self.assertEqual(result["fields"]["callerGender"], "Female")
        self.assertEqual(result["fields"]["callerStatus"], "Separated")
        self.assertEqual(
            result["field_meta"]["callerGender"]["source"], "inference"
        )

    def test_does_not_treat_loneliness_words_as_names(self):
        result = analyze(
            "Caller:\nKamingaw lang gyud. Murag blangko kaayo akong adlaw.\n"
        )

        self.assertEqual(result["fields"]["callerName"], "N/A")

    def test_does_not_treat_bogo_adjective_as_name_or_location(self):
        text = (
            "Responder:\nUnsa may nahitabo?\n\n"
            "Caller:\nBogo kaayo ko sir. Nganong wala man nako na-double check "
            "ang API?\n"
        )

        result = analyze(text)

        self.assertNotEqual(result["fields"]["callerName"], "Bogo")
        self.assertEqual(result["fields"]["callerLocation"], "N/A")

    def test_extracts_bare_location_only_with_a_location_cue(self):
        cases = [
            ("Taga-Bogo ko sir.", "Bogo City"),
            ("Naa ko sa Bogo karon.", "Bogo City"),
            ("I live in Bogo.", "Bogo City"),
        ]

        for text, expected in cases:
            with self.subTest(text=text):
                result = analyze(f"Caller:\n{text}\n")
                self.assertEqual(result["fields"]["callerLocation"], expected)

    def test_maps_specific_dictionary_categories(self):
        cases = [
            (
                "Adto sa barangay o DSWD para mangayo og assistance.",
                ["Others"],
            ),
            (
                "Tawag tag 911 or emergency rescue.",
                ["Referred to Emergency Room"],
            ),
            (
                "Moduol ka sa guidance counselor sa inyong school.",
                ["Referred to Guidance Counselors"],
            ),
            (
                "Naa ba moy guidance counselor o Student Affairs office? "
                "Usahay naay emergency financial assistance programs.",
                ["Referred to Guidance Counselors"],
            ),
        ]

        for text, expected in cases:
            with self.subTest(text=text):
                result = analyze(f"Responder:\n{text}\n")
                self.assertEqual(
                    result["field_meta"]["intervention"]["categories"],
                    expected,
                )


class SummaryTemplateTests(SimpleTestCase):
    def test_builds_exact_four_line_bisaya_summary(self):
        text = (
            "Caller:\n"
            "Nagkurog akong mga kamot miss. Gipaningot kog bugnaw. "
            "Grabe akong anxiety.\n\n"
            "Responder:\n"
            "Kana nga mga kurog ug singot, gitawag na og withdrawal symptoms.\n"
            "Nag-react ang imong lawas kay naanad siya sa alcohol. "
            "Ang severe withdrawal makadaot sa lawas.\n"
            "Mas maayo nga mo-consult ka og doctor. "
            "Naa tay DOH Treatment and Rehabilitation Center sa Mandaue.\n"
        )

        result = analyze(
            text,
            reason_for_calling="Alcohol Dependence",
            risk_assessment="Low Risk",
        )
        lines = result["summary"].splitlines()

        self.assertEqual(len(lines), 4)
        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Alcohol Dependence."
        )
        self.assertEqual(
            lines[1],
            "Gipadayag niya nga gikulbaan, nagkurog ang kamot, ug gipaningot.",
        )
        self.assertEqual(lines[2], "Sa risk assessment, low risk.")
        self.assertEqual(
            lines[3],
            "Ang responder naghatag og referral ug psychoeducation.",
        )

    def test_infers_reason_and_uses_summary_fallbacks(self):
        text = (
            "Caller:\n"
            "Nadawat nako ang email nga wala ko na-renew sa akong scholarship. "
            "Nagsige kog hilak ma'am kay wala na koy kwarta.\n"
        )

        result = analyze(text)
        lines = result["summary"].splitlines()

        self.assertEqual(len(lines), 4)
        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Academic Problem."
        )
        self.assertEqual(
            lines[1], "Gipadayag niya nga nagsige og hilak."
        )
        self.assertEqual(lines[2], "Sa risk assessment, wala pa ma-assess.")
        self.assertEqual(
            lines[3], "Ang responder naghatag og emotional support."
        )

    def test_prefers_textrank_extract_for_reason_and_symptoms(self):
        summary = build_summary(
            "Nagsuka ako. Nagkurog ang kamot. Gipaningot ko. Wala na koy paglaom.",
            summary_text="Nagkurog ang kamot ug gipaningot. Wala na koy paglaom.",
            reason_for_calling="Anxiety",
            risk_assessment="Low Risk",
            max_symptoms=3,
        )

        self.assertIn("tungod sa Anxiety.", summary)
        self.assertIn("nagkurog ang kamot", summary)
        self.assertIn("gipaningot", summary)
        self.assertIn("wala na siyay paglaom", summary)
        self.assertNotIn("nagsuka", summary)

    def test_falls_back_to_full_caller_text_when_extract_has_no_symptoms(self):
        summary = build_summary(
            "Caller text says nagsuka.",
            summary_text="Naa ko sa among balay.",
            reason_for_calling="Anxiety",
            risk_assessment="Low Risk",
        )

        self.assertIn("nagsuka", summary)

    def test_summarizes_empty_nest_loneliness(self):
        text = (
            "Caller:\n"
            "Kamingaw lang gyud. Murag blangko kaayo akong adlaw. "
            "Sige ra kog hilak. Bug-at kaayo akong dughan. "
            "Nawad-an nakog gana mokaon. Kapoy na kaayo mabuhi nga mag-inusara.\n"
        )

        result = analyze(text, risk_assessment="Low Risk")
        lines = result["summary"].splitlines()

        self.assertEqual(
            lines[0],
            "Nitawag ang caller tungod sa Feelings of Sadness and Loneliness.",
        )
        self.assertIn("bug-at ang dughan", lines[1])
        self.assertIn("gikapoy mabuhi", lines[1])
        self.assertIn("nagsige og hilak", lines[1])
        self.assertIn("nawad-an og gana mokaon", lines[1])
        self.assertEqual(lines[2], "Sa risk assessment, low risk.")

    def test_suppresses_passive_death_wish_when_caller_denies_suicide_plan(self):
        text = (
            "Caller:\n"
            "Wala man ko nagplano magpakamatay. Gusto pa ko makakita sa akong "
            "mga apo. Ang akoa lang, mag-ampo ko nga unta matulog ko unya di na "
            "momata. Kapoy na kaayo mabuhi nga mag-inusara.\n"
        )

        result = analyze(text, risk_assessment="Low Risk")

        self.assertNotIn("naglaom nga dili na momata", result["summary"])
        self.assertIn("gikapoy mabuhi", result["summary"])

    def test_keeps_passive_death_wish_without_an_explicit_denial(self):
        result = analyze(
            "Caller:\nMag-ampo ko nga unta matulog ko unya di na momata.\n"
        )

        self.assertIn("naglaom nga dili na momata", result["summary"])

    def test_summarizes_student_insomnia_without_alcohol_false_positive(self):
        text = (
            "Caller:\n"
            "20 anyos na ko, nag-eskwela ko. Three weeks na nga dili gyud ko "
            "katulog og tarong. Makatulog ko pero 3 AM na. Sige ra kog "
            "overthink sa school works. Di nako maka-focus sa discussion. "
            "Dali ra kaayo ko masuko. Ganiha nakahilak na lang ko sa kakapoy.\n"
        )

        result = analyze(text, risk_assessment="Low Risk")
        lines = result["summary"].splitlines()

        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Symptoms of Insomnia."
        )
        self.assertIn("dili makatulog og tarong", lines[1])
        self.assertIn("nagsige og hilak", lines[1])
        self.assertIn("dili maka-focus", lines[1])
        self.assertIn("sige og overthink", lines[1])
        self.assertNotIn("Alcohol Dependence", result["summary"])

    def test_medicine_intake_is_not_alcohol_dependence(self):
        result = analyze(
            "Caller:\n"
            "Nakahunahuna ko mopalit og sleeping pills para makatulog. "
            "Nahadlok ko basin ma-overdose ko sa pag-inom og tambal.\n"
        )

        self.assertNotIn("Alcohol Dependence", result["summary"])
        self.assertIn(
            "Medical/Medication Concern",
            result["summary"],
        )

    def test_textrank_ignores_short_filler_turns(self):
        extract = summarize(
            "Sige miss.\nOo miss.\n"
            "Makatulog ko pero mga 3 AM na unya momata kog 6 AM.",
            max_sentences=3,
            min_words=2,
        )

        self.assertNotIn("Sige miss", extract)
        self.assertNotIn("Oo miss", extract)
        self.assertIn("Makatulog ko", extract)

    def test_summarizes_quarter_life_crisis_and_passive_ideation(self):
        text = (
            "Caller:\n"
            "Murag wa man gud koy padulngan. Naglibog ko sa akong kinabuhi. "
            "Inig open nako sa Facebook, ang uban na-promote na, nangasal na. "
            "Murag na-left behind ko. Dili nako makatulog og tarong. "
            "Magsige kog overthink. Wala koy motivation mobangon. "
            "Makahilak na lang ko kay empty kaayo akong pamati. "
            "Mo-cross sa akong huna-huna usahay, unsa may pulos mabuhi. "
            "Pero hadlok man ko mamatay. Di man sad ko gusto magpakamatay.\n"
        )

        result = analyze(text, risk_assessment="Low Risk")
        lines = result["summary"].splitlines()

        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Quarter Life Crisis."
        )
        for phrase in (
            "nag-ingon nga wala nay pulos mabuhi",
            "dili makatulog og tarong",
            "nagsige og hilak",
            "empty ang pamati",
        ):
            self.assertIn(phrase, lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", result["summary"])

    def test_summarizes_domestic_abuse_without_emergency_false_positive(self):
        text = (
            "Caller:\n"
            "Ako si Elena, 32, babaye, taga Cebu City. Ang akong live-in "
            "partner niabot gikan inom. Gisagpa ko niya duha ka beses unya "
            "gitukmod ko sa bongbong. Sakit kaayo akong abaga. Nagkurog akong "
            "tibuok lawas. Dili ko makaginhawa og tarong. Di ko gusto mamatay.\n\n"
            "Responder:\n"
            "Kailangan ba nato magpadala og rescue? Kung makagawas ka, adto sa "
            "WCPD sa police station para maka-file og blotter ug protection "
            "order. Pwede pud ka mo-adto sa Pink Room sa Vicente Sotto Memorial "
            "Medical Center. Tawag lang balik kung naay emergency.\n"
        )

        result = analyze(
            text,
            reason_for_calling="Domestic Abuse",
            risk_assessment="High Risk",
        )
        lines = result["summary"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Domestic Abuse."
        )
        self.assertIn("gisagpa ug gitukmod", lines[1])
        self.assertIn("sakit ang abaga", lines[1])
        self.assertIn("nagkurog ang lawas", lines[1])
        self.assertNotIn("nagkurog ang kamot", lines[1])
        self.assertNotIn("Referred to Emergency Room", categories)
        self.assertIn("Given Referrals", categories)
        self.assertIn("Others", categories)
        self.assertIn("referral", lines[3])
        self.assertIn("laing tabang", lines[3])

    def test_does_not_match_reason_cues_inside_words_or_negated_suicide(self):
        result = analyze(
            "Caller:\nGamay ra nga butang. Wala sad ko naghunahuna og hikog."
        )
        summary = result["summary"]

        self.assertNotIn("Financial Problem", summary)
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", summary)
        self.assertIn("wala mailhi nga rason", summary)

    def test_summarizes_anger_with_coping_and_referral(self):
        text = (
            "Caller:\n"
            "Ako si Rommel, 34 na ko, taga-Naga City. Hello sir, nanawag ko "
            "kay init kaayo akong ulo. Hadlok ko makapasakit kog tawo. Gamay "
            "ra nga butang pero mobuto akong dughan sa kalagot. Lami kaayo "
            "manumbag. Mamula akong nawong, manginit akong lawas, unya "
            "nagkurog akong mga kamot. Maglabad akong ulo inig human. Wala "
            "sad ko naghunahuna og hikog.\n\n"
            "Responder:\n"
            "Pwede ta mag-breathing exercise. Inhale... exhale. Pwede pud ka "
            "mag-walking away o time-out. Kung open ka, mo-consult sa "
            "psychologist sa Vicente Sotto out-patient department.\n"
        )

        result = analyze(text, risk_assessment="Medium Risk")
        lines = result["summary"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Anger Management Issue."
        )
        self.assertIn("grabeng kasuko", lines[1])
        self.assertIn("mobuto ang dughan", lines[1])
        self.assertIn("gusto manumbag", lines[1])
        self.assertIn("nagkurog ang kamot", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertEqual(lines[2], "Sa risk assessment, medium risk.")
        self.assertIn("Given Referrals", categories)
        self.assertIn("Psychoeducation", categories)
        self.assertIn("referral", lines[3])
        self.assertIn("psychoeducation", lines[3])

    def test_summarizes_cyberbullying_with_active_suicidal_ideation(self):
        text = (
            "Caller:\n"
            "Ako si Janine, 19, babaye, taga-Lapu-Lapu City. Naa nagbuhat og "
            "dummy account sa Facebook, nag-post og edited nga pictures nako "
            "ug hate messages. Nagsuka ko sa sobrang kulba. Nagkurog akong "
            "mga kamot. Dili ko makaginhawa og tarong. Lami na kaayo mamatay. "
            "Nakahunahuna ko muinom og daghang tambal para dili na ko momata "
            "ugma.\n\n"
            "Responder:\n"
            "I-deactivate ang Facebook ug i-turn off ang notifications. "
            "Pag-log out. Ginhawa og lawom. I-report sa school guidance "
            "counselor ug sa Anti-Cybercrime Group sa PNP.\n"
        )

        result = analyze(text, risk_assessment="High Risk")
        lines = result["summary"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Cyberbullying."
        )
        self.assertIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertNotIn("naglaom nga dili na momata", lines[1])
        self.assertIn("gikulbaan", lines[1])
        self.assertIn("dili makaginhawa og tarong", lines[1])
        self.assertEqual(lines[2], "Sa risk assessment, high risk.")
        self.assertIn("Referred to Guidance Counselors", categories)
        self.assertIn("Psychoeducation", categories)
        self.assertIn("Others", categories)
        self.assertIn("guidance counselor", lines[3])
        self.assertIn("psychoeducation", lines[3])
        self.assertIn("laing tabang", lines[3])

    def test_summarizes_postpartum_depression_with_passive_si(self):
        text = (
            "Caller:\n"
            "Ako si Karen, 26, babaye, minyo. Nanganak ko three months ago. "
            "Wala koy ma-feel nga kalipay. Dili ko ganahan mogunit niya. "
            "Kapoy na kaayo akong lawas ug utok. Dili ko katulog. Wala sad "
            "koy gana mokaon. Ako ra usa sa balay, lahi ra ang kamingaw. "
            "Usahay maka-think ko nga mas maayo pa mawala na lang ko. Gusto "
            "lang nako matulog og dugay nga dili na momata.\n\n"
            "Responder:\n"
            "Pwede ta mag-grounding. Inhale... exhale. Kana nga pagbati human "
            "manganak kay postpartum distress. Valid ug matambalan. Mo-consult "
            "sa OB-GYN o psychologist. Tagaan tika og contact numbers sa "
            "clinic.\n"
        )

        result = analyze(text, risk_assessment="Medium Risk")
        lines = result["summary"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Postpartum Depression."
        )
        self.assertIn("naglaom nga dili na momata", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertIn("grabeng kakapoy", lines[1])
        self.assertIn("wala nay kalipay", lines[1])
        self.assertIn("dili makatulog og tarong", lines[1])
        self.assertNotIn("Work/Employment Problem", result["summary"])
        self.assertEqual(lines[2], "Sa risk assessment, medium risk.")
        self.assertIn("Given Referrals", categories)
        self.assertIn("Psychoeducation", categories)
        self.assertIn("referral", lines[3])
        self.assertIn("psychoeducation", lines[3])

    def test_detects_mid_twenties_crisis_psychoeducation(self):
        text = (
            "Responder:\n"
            "Kining imong gibati kay natural nga phase. Usahay tawgon ni nga "
            "mid-twenties crisis. Ang social media nagpakita ra sa best moments "
            "sa uban, mao nang dali ta maka-compare.\n"
        )

        result = analyze(text)

        self.assertIn(
            "Psychoeducation",
            result["field_meta"]["intervention"]["categories"],
        )

    def test_detects_empty_nest_psychoeducation(self):
        text = (
            "Responder:\n"
            "Naa gani nay term sa psychology, gitawag na og empty nest "
            "syndrome. Natural ra nga mag-grief ka.\n"
        )

        result = analyze(text)

        self.assertIn(
            "Psychoeducation",
            result["field_meta"]["intervention"]["categories"],
        )

    def test_pipeline_reports_textrank_template_summary(self):
        result = analyze(
            "Caller:\nNagkurog akong kamot. Gipaningot ko. Grabe akong anxiety."
        )

        self.assertEqual(result["summary_method"], "textrank+template")
        self.assertTrue(result["summary_extract"])


class AnalyzeEndpointTests(SimpleTestCase):
    def test_returns_pipeline_payload_for_json_request(self):
        payload = {
            "text": "Ako si Ana, 25 anyos, babaye, single, taga Cebu City.",
        }

        with patch(
            "apps.callers.views._get_session_user",
            return_value=(object(), None),
        ):
            response = self.client.post(
                reverse("callers:analyze"),
                data=json.dumps(payload),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["fields"]["callerName"], "Ana")
        self.assertEqual(result["fields"]["callerAge"], 25)
        self.assertEqual(result["fields"]["callerGender"], "Female")
        self.assertEqual(result["fields"]["callerStatus"], "Single")
        self.assertEqual(result["fields"]["callerLocation"], "Cebu City")
        self.assertEqual(result["fields"]["intervention"], "N/A")

    def test_passes_manual_reason_and_risk_to_summary(self):
        payload = {
            "text": "Caller:\nNagsige kog hilak ma'am.",
            "reason": "Academic Problem",
            "risk": "High Risk",
        }

        with patch(
            "apps.callers.views._get_session_user",
            return_value=(object(), None),
        ):
            response = self.client.post(
                reverse("callers:analyze"),
                data=json.dumps(payload),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        summary = response.json()["summary"]
        self.assertIn("tungod sa Academic Problem.", summary)
        self.assertIn("Sa risk assessment, high risk.", summary)

    def test_rejects_empty_text(self):
        with patch(
            "apps.callers.views._get_session_user",
            return_value=(object(), None),
        ):
            response = self.client.post(
                reverse("callers:analyze"),
                data=json.dumps({"text": "   "}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "error")
