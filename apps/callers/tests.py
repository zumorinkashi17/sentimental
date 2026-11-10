import json
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse

from .nlp import analyze
from .nlp.summary import build_summary, translate_summary
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

        self.assertTrue(result["summary_bisaya"])
        self.assertGreater(len(result["summary_bisaya"]), 20)

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

    def test_parses_bisaya_compound_age_with_apostrophe(self):
        result = analyze("Caller:\nAko si Anton. Kwarenta'y singko na ko sir.")

        self.assertEqual(result["fields"]["callerName"], "Anton")
        self.assertEqual(result["fields"]["callerAge"], 45)

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

    def test_auto_fills_common_intervention_phrases(self):
        cases = [
            ("I recommend counseling and therapy.", ["Given Referrals"]),
            (
                "I will endorse you to our partner facility.",
                ["Given Referrals"],
            ),
            ("You should see a therapist.", ["Given Referrals"]),
            ("We can provide financial assistance.", ["Others"]),
            ("I will transfer you to the crisis hotline.", ["Others"]),
            ("Let us create a safety plan for you.", ["Others"]),
            (
                "I understand. You are not alone, take care.",
                ["Responder provided empathetic listening and support"],
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
        lines = result["summary_bisaya"].splitlines()

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

    def test_translates_generated_summary_to_english(self):
        text = (
            "Caller:\n"
            "Nagkurog akong kamot. Gipaningot ko.\n\n"
            "Responder:\n"
            "Pwede tika i-refer sa psychiatrist ug maghatag og "
            "psychoeducation bahin sa imong kondisyon.\n"
        )

        result = analyze(
            text,
            reason_for_calling="Anxiety",
            risk_assessment="High Risk",
        )
        english = result["summary"].splitlines()
        bisaya = result["summary_bisaya"].splitlines()

        self.assertEqual(len(english), 4)
        self.assertEqual(
            english[0], "The caller reached out due to Anxiety."
        )
        self.assertIn("hand trembling", english[1])
        self.assertIn("sweating", english[1])
        self.assertEqual(
            english[2], "In the risk assessment, high risk."
        )
        self.assertIn("provided a referral", english[3])
        self.assertIn("psychoeducation", english[3])
        self.assertTrue(bisaya[0].startswith("Nitawag ang caller"))
        self.assertIn("nagkurog ang kamot", bisaya[1])

    def test_excludes_reported_third_party_symptoms(self):
        text = (
            "Caller:\n"
            "Pwede ba ko manawag bisan dili ako ang naay problema? "
            "Bahin ni sa akong amigo gud. Nag-panic na gyud ko. "
            "Gikulbaan ko. Nagkurog akong kamot. "
            "Nagsakit akong tiyan sa kakulba. "
            "Niingon siya nako atong Dominggo nga kapoy na daw kaayo mabuhi.\n\n"
            "Responder:\n"
            "Pwede tika i-refer sa psychiatrist ug maghatag og psychoeducation.\n"
        )

        result = analyze(text, risk_assessment="Low Risk")

        self.assertIn("stomach pain", result["summary"])
        self.assertNotIn("fatigue", result["summary"])
        self.assertNotIn("gikapoy", result["summary_bisaya"])

    def test_translates_passive_death_wish_and_unassessed_risk(self):
        summary = build_summary(
            "Caller:\nMag-ampo ko nga dili na lang unta ko makamata.\n",
            reason_for_calling="Depression",
        )

        english = translate_summary(summary)

        self.assertIn("hoping not to wake up", english)
        self.assertIn("In the risk assessment, not yet assessed.", english)
        self.assertEqual(len(english.splitlines()), 4)

    def test_infers_reason_and_uses_summary_fallbacks(self):
        text = (
            "Caller:\n"
            "Nadawat nako ang email nga wala ko na-renew sa akong scholarship. "
            "Nagsige kog hilak ma'am kay wala na koy kwarta.\n"
        )

        result = analyze(text)
        lines = result["summary_bisaya"].splitlines()

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
        lines = result["summary_bisaya"].splitlines()

        self.assertEqual(
            lines[0],
            "Nitawag ang caller tungod sa Feelings of Sadness and Loneliness.",
        )
        self.assertIn("bug-at ang dughan", lines[1])
        self.assertIn("gikapoy mabuhi", lines[1])
        self.assertIn("nagsige og hilak", lines[1])
        self.assertIn("nawad-an og gana mokaon", lines[1])
        self.assertEqual(lines[2], "Sa risk assessment, low risk.")

    def test_keeps_passive_death_wish_when_caller_denies_active_plan(self):
        text = (
            "Caller:\n"
            "Wala man ko nagplano magpakamatay. Gusto pa ko makakita sa akong "
            "mga apo. Ang akoa lang, mag-ampo ko nga unta matulog ko unya di na "
            "momata. Kapoy na kaayo mabuhi nga mag-inusara.\n"
        )

        result = analyze(text, risk_assessment="Low Risk")

        self.assertIn("naglaom nga dili na momata", result["summary_bisaya"])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", result["summary_bisaya"])
        self.assertIn("gikapoy mabuhi", result["summary_bisaya"])

    def test_keeps_passive_death_wish_without_an_explicit_denial(self):
        result = analyze(
            "Caller:\nMag-ampo ko nga unta matulog ko unya di na momata.\n"
        )

        self.assertIn("naglaom nga dili na momata", result["summary_bisaya"])

    def test_summarizes_student_insomnia_without_alcohol_false_positive(self):
        text = (
            "Caller:\n"
            "20 anyos na ko, nag-eskwela ko. Three weeks na nga dili gyud ko "
            "katulog og tarong. Makatulog ko pero 3 AM na. Sige ra kog "
            "overthink sa school works. Di nako maka-focus sa discussion. "
            "Dali ra kaayo ko masuko. Ganiha nakahilak na lang ko sa kakapoy.\n"
        )

        result = analyze(text, risk_assessment="Low Risk")
        lines = result["summary_bisaya"].splitlines()

        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Symptoms of Insomnia."
        )
        self.assertIn("dili makatulog og tarong", lines[1])
        self.assertIn("nagsige og hilak", lines[1])
        self.assertIn("dili maka-focus", lines[1])
        self.assertIn("sige og overthink", lines[1])
        self.assertNotIn("Alcohol Dependence", result["summary_bisaya"])

    def test_summarizes_academic_pressure_with_passive_ideation(self):
        text = (
            "Caller:\n"
            "Jelo lang sir. Baynte sir. Naa ko sa Talamban karon nag-board. "
            "Tungod sa skwela sir. Murag ma-drop na nako ang duha nako ka "
            "major subjects. Daghan kaayo kog backlogs. Na-anxious ko. "
            "Lisod kaayo ko katulog. Usahay magkurog akong kamot. "
            "Wala na koy gana mokaon. Usahay maka-isip ko nga murag lami na "
            "lang matulog unya dili na momata. Pero hadlok man ko mamatay.\n\n"
            "Responder:\n"
            "Pwede ka mo-adto sa guidance counselor. Mag-breathing exercise ta.\n"
        )

        result = analyze(text, risk_assessment="Low Risk")
        lines = result["summary_bisaya"].splitlines()

        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Academic Problem."
        )
        self.assertIn("naglaom nga dili na momata", lines[1])
        self.assertIn("gikulbaan", lines[1])
        self.assertIn("dili makatulog og tarong", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])

    def test_summarizes_bullying_without_false_location_or_guilt(self):
        text = (
            "Caller:\n"
            "Miko akong ngalan. Ayaw na lang ko pangutan-a sa akong edad. "
            "Lalaki baya unta ko pero nag-sige kog hilak diri sa CR sa school "
            "namo. Ang akong mga classmates sige'g kuhaon akong bag unya "
            "ilabay sa basurahan. Gi-suwat-suwatan nila akong notebook og "
            "'Bogo', 'Luod'. Taga-adlaw ko nila kanchawan. Gikumot akong tiyan "
            "sa kulba. Wa nakoy gana mokaon. Kalit lang ko mag-kurog. "
            "Naka-isip ko nga kung ambak na lang kaha ko. Basin ma-guilty na "
            "sila. Pero nahadlok ko mamatay.\n\n"
            "Responder:\n"
            "Pwede ka mo-adto sa guidance counselor. Mag-breathing exercise ta.\n"
        )

        result = analyze(text, risk_assessment="High Risk")
        lines = result["summary_bisaya"].splitlines()

        self.assertEqual(result["fields"]["callerLocation"], "N/A")
        self.assertEqual(result["fields"]["callerGender"], "Male")
        self.assertEqual(lines[0], "Nitawag ang caller tungod sa Bullying.")
        self.assertIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertNotIn("makonsensya", lines[1])
        self.assertNotIn("guilt", result["summary"])

    def test_medicine_intake_is_not_alcohol_dependence(self):
        result = analyze(
            "Caller:\n"
            "Nakahunahuna ko mopalit og sleeping pills para makatulog. "
            "Nahadlok ko basin ma-overdose ko sa pag-inom og tambal.\n"
        )

        self.assertNotIn("Alcohol Dependence", result["summary_bisaya"])
        self.assertIn(
            "Medical/Medication Concern",
            result["summary_bisaya"],
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
        lines = result["summary_bisaya"].splitlines()

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
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", result["summary_bisaya"])

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
        lines = result["summary_bisaya"].splitlines()
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
        summary = result["summary_bisaya"]

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
        lines = result["summary_bisaya"].splitlines()
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

    def test_breakup_with_active_si_and_chest_pain(self):
        text = (
            "Caller:\n"
            "Ken akong name, 21, lalaki, single. Gibuwagan ko sa akong uyab. "
            "Sakit kaayo akong dughan. Wala ko nikaon. Nagsuka ko ganinang "
            "udto tungod sa grabe nakong hilak. Nag-kurog akong lawas. "
            "Naka-huna-huna ko nga unsa kaha kung i-bangga nako ni sa truck "
            "aron mahuman na lang tanan. Pero nipauli ko. Di ko gusto "
            "mag-inusara sa kwarto.\n\n"
            "Responder:\n"
            "Mag-grounding ta. Valid ang imong gibati. Pwede tika tagaan og "
            "contacts sa psychologist o guidance counselor.\n\n"
            "Caller:\n"
            "Murag di pa ko ready makig-estorya face-to-face.\n"
        )

        result = analyze(text, risk_assessment="High Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "Ken")
        self.assertEqual(result["fields"]["callerAge"], 21)
        self.assertEqual(result["fields"]["callerGender"], "Male")
        self.assertEqual(result["fields"]["callerStatus"], "Single")
        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Relationship Problem."
        )
        self.assertIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertIn("sakit ang dughan", lines[1])
        self.assertNotIn("nag-inusara", lines[1])
        self.assertEqual(lines[2], "Sa risk assessment, high risk.")
        self.assertIn("Given Referrals", categories)
        self.assertIn("Refused Referrals", categories)
        self.assertIn("Psychoeducation", categories)

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
        lines = result["summary_bisaya"].splitlines()
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
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Postpartum Depression."
        )
        self.assertIn("naglaom nga dili na momata", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertIn("grabeng kakapoy", lines[1])
        self.assertIn("wala nay kalipay", lines[1])
        self.assertIn("dili makatulog og tarong", lines[1])
        self.assertNotIn("Work/Employment Problem", result["summary_bisaya"])
        self.assertEqual(lines[2], "Sa risk assessment, medium risk.")
        self.assertIn("Given Referrals", categories)
        self.assertIn("Psychoeducation", categories)
        self.assertIn("referral", lines[3])
        self.assertIn("psychoeducation", lines[3])

    def test_label_less_phase_transcript_keeps_caller_and_responder_turns(self):
        text = (
            "[PHASE 1 - OPENING]\n\n"
            "Maayong buntag, Tawag Paglaum. Ako si Anton. Unsa man akong "
            "ikatabang nimo karon?\n\n"
            "(Sniffles) Hello, sir... Wala na ko kabalo unsaon nako ni.\n\n"
            "[PHASE 2 - CALLER IDENTIFICATION]\n\n"
            "Karen akong ngalan, sir.\n\n"
            "Salamat, Karen. Pila na may imong edad karon?\n\n"
            "26 na ko sir. Oo, babaye ko ug minyo na.\n\n"
            "[PHASE 3 - PROBLEM EXPLORATION]\n\n"
            "Nanganak man gud ko sir, three months ago. Wala koy ma-feel nga "
            "kalipay.\n\n"
            "Karen, paminaw nako. Dili ka bati nga inahan.\n\n"
            "[PHASE 4 - EMOTIONAL ASSESSMENT]\n\n"
            "Pero ako ra man usa sa balay magbantay sir kay nag-work man akong "
            "bana. Lahi ra gyud ang kamingaw.\n\n"
            "Bug-at gyud nang ikaw ra usa. Kamusta man ang imong pagkatulog o "
            "pagkaon?\n\n"
            "Dili ko katulog sir. Bisan og natulog na ang baby, magmata ra "
            "gihapon ko nag-sige og overthink. Wala sad koy gana mokaon.\n\n"
            "[PHASE 5 - RISK ASSESSMENT]\n\n"
            "Kanang grabeng kakapoy, niabot ba sa punto nga nakahunahuna ka "
            "nga pasakitan ang imong baby? O kaha tapuson ang imong kinabuhi?\n\n"
            "Dili nako pasakitan akong baby sir. Pero sa akong kaugalingon... "
            "usahay maka-think ko nga basin mas maayo pa mawala na lang ko. "
            "Gusto lang nako matulog og dugay nga dili na momata.\n\n"
            "[PHASE 6 - INTERVENTION]\n\n"
            "Pwede ta mag-grounding. Inhale... exhale. Kana nga pagbati human "
            "manganak kay postpartum distress. Valid ug matambalan.\n\n"
            "Wala gyud ko kabalo unsaon ni sir. Naulaw sad ko mo-sulti sa "
            "akong bana.\n\n"
            "[PHASE 7 - RESOURCE INFORMATION]\n\n"
            "Dili ka angay maulaw sa imong bana. Pwede ba nimo siya "
            "ma-text?\n\n"
            "Basin... basin pwede nako siya i-chat karon sir.\n\n"
            "Mas maayo gyud nga ma-consult nimo balik ang imong OB-GYN o kaha "
            "maka-adto ka og psychologist. Tagaan tika og contact numbers sa "
            "clinic.\n\n"
            "[PHASE 8 - CLOSING]\n\n"
            "Sige sir, palihug ko og send sa numbers.\n\n"
            "Walay sapayan, Karen. Amping kanunay.\n"
        )

        result = analyze(text, risk_assessment="Medium Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "Karen")
        self.assertEqual(result["fields"]["callerAge"], 26)
        self.assertEqual(result["fields"]["callerGender"], "Female")
        self.assertEqual(result["fields"]["callerStatus"], "Married")
        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Postpartum Depression."
        )
        self.assertIn("naglaom nga dili na momata", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertIn("dili makatulog og tarong", lines[1])
        self.assertEqual(lines[2], "Sa risk assessment, medium risk.")
        self.assertIn("Given Referrals", categories)
        self.assertIn("Psychoeducation", categories)

    def test_summarizes_panic_attack_without_er_false_positive(self):
        text = (
            "Caller:\n"
            "K-Klara ma'am... babaye ko... di ko kaginhawa... murag "
            "ma-heart attack ko... sakit akong dughan... gikulbaan ko... "
            "nagmaneho unta ko unya kalit lang nagtuyok akong panan-aw.\n\n"
            "Responder:\n"
            "Klara, nag-react lang og maayo ang imong lawas. Gawas sa "
            "pagpitik og kusog sa kasingkasing ug paghuot sa dughan, "
            "namugnaw ba imong mga kamot?\n\n"
            "Caller:\n"
            "Nangurog ko... nanghagdaw akong mga tudlo... lipong kaayo ko. "
            "Hadlok ko mawad-an og panimuot diri nga ako ra usa.\n\n"
            "Responder:\n"
            "Kana nga pagbati kay panic attack. Normal ra ni nga reaksyon sa "
            "anxiety ug stress. Mas maayo nga maka-istorya ka og psychologist "
            "aron matabangan ka, dili lang ig-abot na sa ER. Tagaan tika og "
            "referral ug contact number. Mag-dungan ta og ginhawa.\n\n"
            "Caller:\n"
            "Sige ma'am. Dili usa ko mo-drive ron, tawagan nako akong bana "
            "para siyay mokuha nako.\n"
        )

        result = analyze(text, risk_assessment="Medium Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "Klara")
        self.assertEqual(result["fields"]["callerGender"], "Female")
        self.assertEqual(result["fields"]["callerStatus"], "Married")
        self.assertEqual(lines[0], "Nitawag ang caller tungod sa Panic Attack.")
        self.assertIn("sakit ang dughan", lines[1])
        self.assertIn("gikulbaan", lines[1])
        self.assertEqual(lines[2], "Sa risk assessment, medium risk.")
        self.assertNotIn("Referred to Emergency Room", categories)
        self.assertIn("Given Referrals", categories)
        self.assertIn("Psychoeducation", categories)
        self.assertNotIn("emergency room", lines[3])

    def test_summarizes_grief_with_pseudonym_and_refused_referral(self):
        text = (
            "Caller:\n"
            "Tawga lang kog 'Inday', ma'am. Usa ko ka babaye pero dili lang ko "
            "mosulti sa akong tinuod nga ngalan. Diri ra ko sa Cebu City. "
            "Gilubong siya gahapon... akong papa. Wala na siya. Magmata ko "
            "inig kadlawon. Wala gyud koy gana ibangon sa katre or mokaon. "
            "Nagsige ko og hilak. Murag empty ang pamati. Usahay mag-ampo ko "
            "nga kuhaon na lang sad unta ko niya, pero dili nako hikugon "
            "akong kaugalingon.\n\n"
            "Responder:\n"
            "Valid ang imong gibati. Normal ra nga maglagot ka. Walay timeframe "
            "ang pag-move on. Naa tay support groups ug psychologist nga pwede "
            "ma-refer nimo.\n\n"
            "Caller:\n"
            "Dili usa nang sa psychologist ma'am, dili pa ko ganahan mogawas "
            "sa kwarto ron.\n"
        )

        result = analyze(text, risk_assessment="High Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "Inday")
        self.assertEqual(result["fields"]["callerAge"], "N/A")
        self.assertEqual(result["fields"]["callerGender"], "Female")
        self.assertEqual(result["fields"]["callerStatus"], "N/A")
        self.assertEqual(result["fields"]["callerLocation"], "Cebu City")
        self.assertEqual(lines[0], "Nitawag ang caller tungod sa Grief.")
        self.assertIn("dili makatulog og tarong", lines[1])
        self.assertIn("nagsige og hilak", lines[1])
        self.assertIn("nawad-an og gana mokaon", lines[1])
        self.assertIn("empty ang pamati", lines[1])
        self.assertNotIn("Family Problem", result["summary_bisaya"])
        self.assertEqual(lines[2], "Sa risk assessment, high risk.")
        self.assertIn("Given Referrals", categories)
        self.assertIn("Refused Referrals", categories)
        self.assertIn("Psychoeducation", categories)
        self.assertIn("referral", lines[3])
        self.assertIn("wala pa kini dawata", lines[3])
        self.assertIn("psychoeducation", lines[3])

    def test_keeps_full_anonymity_and_manual_quarter_life_crisis(self):
        text = (
            "Caller:\n"
            "Pwede ba nga completely anonymous ko? Dili lang ko mu-share ug "
            "bisan unsa—name, age, gender, bisan taga-asa ko.\n\n"
            "Responder:\n"
            "Wala nay problema. Unsaon nako pagtawag nimo?\n\n"
            "Caller:\n"
            "\"Caller\" na lang gyud. Murag nawala ko. Dili ko kabalo asa "
            "padulong akong kinabuhi. Gikapoy na ko. Wala nako makita ang "
            "purpose sa tanan. Sige'g kurog akong dughan. Dili nako katulog. "
            "Sige kog overthink. Wala ko nag-isip nga patyon akong "
            "kaugalingon.\n\n"
            "Responder:\n"
            "Normal ra nga phase ni. Pwede ka mag-social media detox. Naa "
            "mga career counselors o life coaches nga pwede nimo ma-istorya.\n"
        )

        result = analyze(
            text,
            reason_for_calling="Quarter Life Crisis",
            risk_assessment="Low Risk",
        )
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "N/A")
        self.assertEqual(result["fields"]["callerAge"], "N/A")
        self.assertEqual(result["fields"]["callerGender"], "N/A")
        self.assertEqual(result["fields"]["callerStatus"], "N/A")
        self.assertEqual(result["fields"]["callerLocation"], "N/A")
        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Quarter Life Crisis."
        )
        self.assertIn("dili makatulog og tarong", lines[1])
        self.assertIn("nawala ang purpose", lines[1])
        self.assertIn("nagkurog ang dughan", lines[1])
        self.assertIn("sige og overthink", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertEqual(lines[2], "Sa risk assessment, low risk.")
        self.assertIn("Given Referrals", categories)
        self.assertIn("Psychoeducation", categories)

    def test_summarizes_financial_crisis_with_passive_si(self):
        text = (
            "Caller:\n"
            "Anton diay sir. Kwarenta'y singko na ko. Lisod kaayo pangitaon "
            "asa mukuha ug kwarta ron. Nawad-an kog trabaho last month. Hapit "
            "na ang due date sa among abang. Akong asawa nasakit ug kailangan "
            "og tambal. Na-pressure ko kay isip amahan ug bana, ako untay "
            "mag-provide nila pero wala koy mabuhat. Grabe akong overthink "
            "taga gabii. Duha na ka semana nga tag-usa o duha ka oras ra akong "
            "tulog. Usahay kalit lang mu-kurog akong mga kamot. Kahuot ang "
            "akong dughan. Niagi sa akong huna-huna kadali nga kung mawala na "
            "lang ko, basig makuhaan ang problema sa akong asawa. Pero di ko "
            "gusto mubiya nila.\n\n"
            "Responder:\n"
            "Valid ang imong gibati. Normal ra nga ma-pressure ka. Pwede ta "
            "mag-deep breathing. Naa tay DSWD, barangay health center, social "
            "worker, ug psychologist nga pwede ma-refer nimo.\n\n"
            "Caller:\n"
            "Dili lang sa siguro nang sa psychologist sir, kay kwarta man gyud "
            "among labing kinahanglan karon.\n"
        )

        result = analyze(text, risk_assessment="High Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "Anton")
        self.assertEqual(result["fields"]["callerAge"], 45)
        self.assertEqual(result["fields"]["callerGender"], "Male")
        self.assertEqual(result["fields"]["callerStatus"], "Married")
        self.assertEqual(result["fields"]["callerLocation"], "N/A")
        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Financial Problem."
        )
        self.assertIn("naglaom nga dili na momata", lines[1])
        self.assertIn("dili makatulog og tarong", lines[1])
        self.assertIn("mobuto ang dughan", lines[1])
        self.assertIn("nagkurog ang kamot", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertEqual(lines[2], "Sa risk assessment, high risk.")
        self.assertIn("Given Referrals", categories)
        self.assertIn("Refused Referrals", categories)
        self.assertIn("Psychoeducation", categories)
        self.assertIn("Others", categories)
        self.assertIn("referral", lines[3])
        self.assertIn("wala pa kini dawata", lines[3])
        self.assertIn("psychoeducation", lines[3])
        self.assertIn("laing tabang", lines[3])

    def test_handles_anonymous_fire_trauma_with_active_si(self):
        text = (
            "Caller:\n"
            "Lalaki ko sir, taga Cebu City. Ayaw na lang ko pangutana sa "
            "akong ngalan ug edad. Nasunog among balay gahapon. Gikasilagan "
            "ko nila. Gidumtan ko sa akong papa. Nagsakit kaayo akong dughan "
            "ron. Murag gikumot akong kasingkasing. Sukad gahapon wala ko "
            "katulog ug wala ko nakaon. Nagsige og hilak ko. Lami kaayo "
            "ihapak akong kaugalingon. Nakatan-aw nako sa mga nag-dagan nga "
            "truck. Naka-isip ko nga og magpaligis na lang kaha ko. Pero "
            "ni-atras ko.\n\n"
            "Responder:\n"
            "Normal ra nga dili pa nimo mapatawad imong sarili karon. "
            "Pag-ginhawa og lawom. Pwede kang muduol sa social workers sa "
            "inyong barangay o DSWD ugma para makapangayo og psychological "
            "first aid.\n"
        )

        result = analyze(text, risk_assessment="High Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "N/A")
        self.assertEqual(result["fields"]["callerAge"], "N/A")
        self.assertEqual(result["fields"]["callerGender"], "Male")
        self.assertEqual(result["fields"]["callerStatus"], "N/A")
        self.assertEqual(result["fields"]["callerLocation"], "Cebu City")
        self.assertEqual(lines[0], "Nitawag ang caller tungod sa Trauma.")
        self.assertNotIn("Inquiry", lines[0])
        self.assertIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertIn("sakit ang dughan", lines[1])
        self.assertIn("dili makatulog og tarong", lines[1])
        self.assertEqual(lines[2], "Sa risk assessment, high risk.")
        self.assertIn("Given Referrals", categories)
        self.assertIn("Psychoeducation", categories)
        self.assertIn("Others", categories)
        self.assertIn("referral", lines[3])
        self.assertIn("psychoeducation", lines[3])
        self.assertIn("laing tabang", lines[3])

    def test_handles_caregiver_burnout_with_self_harm_ideation(self):
        text = (
            "Caller:\n"
            "Tawga lang ko'g 'K' ma'am. Dili ko gusto magpaila kay maulaw "
            "ko. 30 anyos ko ma'am. Minyo ko. Pero ayaw na lang ko pangutana "
            "taga-asa ko ma'am or unsa akong gender ha? Naghilak ko'g maayo "
            "ma'am, ug wa na ko ni-stop og hilak. Murag nibuto na lang kalit "
            "akong dughan. Ako man gud tanan nag-dala ma'am. Sa balay, akong "
            "asawa natangtang sa trabaho. Sa trabaho nako, perti "
            "ka-demanding sa akong boss. Puno na kaayo ko. Nagkurog akong "
            "tuhod ug nanghagdaw akong mga kamot. Nagsakit akong totonlan. "
            "Murag empty kaayo ko sa sulod. Naka-tan-aw ko sa bildo ug "
            "naka-huna-huna ko'g lami ihapak akong ulo sa bungbong o garasan "
            "akong kaugalingon. Pero wala nako gihimo.\n\n"
            "Responder:\n"
            "Valid kaayo imong gibati. Ginhawa og lawom. Naa tay mga "
            "psychologist nga pwede nato ma-refer nimo.\n"
        )

        result = analyze(text, risk_assessment="Medium Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "K")
        self.assertEqual(result["fields"]["callerAge"], 30)
        self.assertEqual(result["fields"]["callerGender"], "N/A")
        self.assertEqual(result["fields"]["callerStatus"], "Married")
        self.assertEqual(result["fields"]["callerLocation"], "N/A")
        self.assertEqual(lines[0], "Nitawag ang caller tungod sa Burnout.")
        self.assertNotIn("Marital Problem", lines[0])
        self.assertIn(
            "adunay mga hunahuna sa pagpasakit sa kaugalingon", lines[1]
        )
        self.assertIn("mobuto ang dughan", lines[1])
        self.assertIn("nagsige og hilak", lines[1])
        self.assertIn("empty ang pamati", lines[1])
        self.assertNotIn("pagpakamatay", lines[1])
        self.assertEqual(lines[2], "Sa risk assessment, medium risk.")
        self.assertIn("Given Referrals", categories)
        self.assertIn("Psychoeducation", categories)
        self.assertIn("referral", lines[3])
        self.assertIn("psychoeducation", lines[3])

    def test_label_less_domestic_abuse_uses_caller_pseudonym(self):
        text = (
            "[PHASE 1 – OPENING]\n\n"
            "Maayong gabii, Tawag Paglaum ni. Ako si Anna. Unsa man ang "
            "akong ikatabang nimo?\n\n"
            "*whispering* Hello? Ma'am... open pa mo ron? Pwede ko "
            "mangayo'g tabang?\n\n"
            "[PHASE 2 – RAPPORT BUILDING]\n\n"
            "Oo, open mi 24/7. Andam ko maminaw ug motabang nimo. Safe ra ba "
            "ka diha?\n\n"
            "Nagtago ko ma'am... naa ko sulod sa banyo ron. Nagkurog ko "
            "ma'am.\n\n"
            "[PHASE 3 – CALLER IDENTIFICATION]\n\n"
            "Pwede ko makabalo unsay akong itawag nimo?\n\n"
            "Di ko musulti taga-asa ko ma'am! Tawga lang ko'g Elena. Dili na "
            "nako tinuod ngalan ma'am. Usa ko ka asawa nga gusto lang "
            "mabuhi.\n\n"
            "[PHASE 4 – PROBLEM EXPLORATION]\n\n"
            "Unsa may nahitabo?\n\n"
            "Akong bana, ma'am. Niuli siya nga hubog. Gisumbag ko niya sa "
            "aping. Katulo ko niya gisagpa unya gilabayan ko niya'g plato. "
            "Kulatahon na sad ko niya.\n\n"
            "[PHASE 5 – EMOTIONAL ASSESSMENT]\n\n"
            "Kumusta ang imong gibati sa imong lawas?\n\n"
            "Naghubag akong aping ma'am. Akong dughan murag mubuto sa "
            "kakulba. Di ko kaginhawa'g tarong. Mahadlok na ko inig gabii.\n\n"
            "[PHASE 6 – RISK ASSESSMENT]\n\n"
            "Nipasok ba sa imong huna-huna nga gusto na lang nimo mawala o "
            "tapuson ang imong kinabuhi?\n\n"
            "Dili ma'am! Gusto ko mabuhi. Dili ko gusto magpakamatay. Gusto "
            "ra ko maka-ikyas niya.\n\n"
            "[PHASE 7 – INTERVENTION]\n\n"
            "Kalmahon nimo imong pag-ginhawa. Ginhawa agi sa imong ilong... "
            "pag-exhale... para moubos ang panic.\n\n"
            "Okay ma'am.\n\n"
            "[PHASE 8 – RESOURCE INFORMATION]\n\n"
            "Pwede ka modangop sa WCPD sa inyong barangay o DSWD. "
            "Makahatag sila og protection order.\n\n"
            "Salamat ma'am.\n\n"
            "[PHASE 9 – CLOSING]\n\n"
            "Pag-amping, Elena.\n\n"
            "Dako kaayong salamat, ma'am Anna.\n"
        )

        result = analyze(text, risk_assessment="High Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "Elena")
        self.assertEqual(result["fields"]["callerAge"], "N/A")
        self.assertEqual(result["fields"]["callerGender"], "Female")
        self.assertEqual(result["fields"]["callerStatus"], "Married")
        self.assertEqual(result["fields"]["callerLocation"], "N/A")
        self.assertEqual(lines[0], "Nitawag ang caller tungod sa Domestic Abuse.")
        self.assertNotIn("Marital Problem", lines[0])
        self.assertIn("gisagpa ug gitukmod", lines[1])
        self.assertIn("naghubag ang aping", lines[1])
        self.assertIn("mobuto ang dughan", lines[1])
        self.assertIn("gikulbaan", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertEqual(lines[2], "Sa risk assessment, high risk.")
        self.assertIn("Psychoeducation", categories)
        self.assertIn("Others", categories)
        self.assertIn("psychoeducation", lines[3])
        self.assertIn("laing tabang", lines[3])

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

    def test_rejects_non_name_and_canonicalizes_davao(self):
        text = (
            "Caller:\n"
            "(crying) Dili na nako kaya. Wala na koy paglaom. Murag mobuto "
            "akong dughan. Naglisod kog ginhawa. Gikulbaan ko. Nakaginhawa "
            "na ko og tarong karon. 25 na ko, diri ko sa Davao nagpuyo. "
            "Single ko ma'am.\n"
        )

        result = analyze(text, risk_assessment="Medium Risk")

        self.assertEqual(result["fields"]["callerName"], "N/A")
        self.assertEqual(result["fields"]["callerLocation"], "Davao City")
        self.assertIn("dili makaginhawa", result["summary_bisaya"])
        self.assertIn("gikulbaan", result["summary_bisaya"])

    def test_ignores_location_mentioned_only_as_workplace(self):
        result = analyze(
            "Caller:\n25 na ko, diri ko sa Davao nag-work karon. Single ko.\n"
        )

        self.assertEqual(result["fields"]["callerLocation"], "N/A")

    def test_handles_label_less_phase_transcript(self):
        text = (
            "[PHASE 1 - OPENING]\n\n"
            "Maayong gabii, Tawag Paglaum ni. Ako si Trisha. Unsa man akong "
            "matabang nimo?\n\n"
            "(Whispering) Hello miss... tabangi ko. Nagtago ko sa CR.\n\n"
            "[PHASE 2 - PROBLEM EXPLORATION]\n\n"
            "Okay, sultihi ko unsay nahitabo. Ngano nanapat siya nimo?\n\n"
            "Ang akong live-in partner miss, niabot siya gikan inom. Ako si "
            "Elena. Babaye ko. Gisagpa ko niya ug gitukmod ko sa bongbong. "
            "32 na ko, sa Cebu City ra ko nagpuyo.\n\n"
            "[PHASE 3 - RISK ASSESSMENT]\n\n"
            "Mao lagi miss. Kapoy na kaayo ko. Di ko gusto mamatay.\n\n"
            "Naa ba kay kapamilya o kaila nga pwede nimo maduolan?\n\n"
            "Naa koy igsoon sa Mandaue. Mo-refer ko nimo sa guidance "
            "counselor ug mag-breathing exercise ta.\n"
        )

        result = analyze(text, risk_assessment="High Risk")

        self.assertEqual(result["fields"]["callerName"], "Elena")
        self.assertEqual(result["fields"]["callerAge"], 32)
        self.assertEqual(result["fields"]["callerGender"], "Female")
        self.assertEqual(result["fields"]["callerLocation"], "Cebu City")
        self.assertIn("tungod sa Domestic Abuse.", result["summary_bisaya"])
        self.assertNotIn("Anger Management Issue", result["summary_bisaya"])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", result["summary_bisaya"])

    def test_work_stress_with_passive_give_up_is_not_suicidal_ideation(self):
        text = (
            "Caller:\n"
            "Kapoy na kaayo ko. Murag lami na i-give up tanan. Di na ko "
            "kabalo unsaon pag-agwanta. Kani akong trabaho sa BPO, toxic "
            "akong TL, sige mi overtime. Wala na koy tulog tarong. Kulbaan "
            "ko, nagsige kog hilak, bugnaw akong singot. Wala man hinuon ko "
            "naghunahuna og hikog. Gusto lang ko maka-ikyas sa trabaho, "
            "dili sa kinabuhi. Dili lang sa guro ma'am.\n\n"
            "Responder:\n"
            "Nagtanyag ko og referral sa psychologist. Mag-breathing "
            "exercise ta para sa imong stress ug anxiety.\n"
        )

        result = analyze(text, risk_assessment="Medium Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Work/Employment Problem."
        )
        self.assertIn("gikulbaan", lines[1])
        self.assertIn("nagsige og hilak", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertIn("Given Referrals", categories)
        self.assertIn("Refused Referrals", categories)
        self.assertIn("Psychoeducation", categories)
        self.assertIn("nagtanyag og referral", lines[3])
        self.assertIn("wala pa kini dawata sa caller", lines[3])
        self.assertNotIn("responder wala modawat sa referral", lines[3])

    def test_academic_burnout_extracts_physical_symptoms(self):
        text = (
            "Caller:\n"
            "Kevin lang. 19 na ko. Sa Talisay ko nagpuyo. Lalaki ko. Sa "
            "school ni siya, daghan mig plates ug midterms. Dili na ko "
            "kasabot sa akong utok. Sige kog puyat ug nagsige kog hilak. "
            "Lisod kaayo ko ginhawa usahay. Murag naay nagtuok sa akong "
            "kasing-kasing. Wala na koy gana mokaon. Wala na koy tulog "
            "tarong. Wala man hinuon. Dili ko gusto mamatay. Dili lang sa "
            "guro karon.\n\n"
            "Responder:\n"
            "Naa ba moy guidance counselor? Pwede tika tagaan ug contact sa "
            "psychologist. Mag-breathing exercise ta para sa imong stress.\n"
        )

        result = analyze(text, risk_assessment="Medium Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "Kevin")
        self.assertEqual(result["fields"]["callerAge"], 19)
        self.assertEqual(result["fields"]["callerGender"], "Male")
        self.assertEqual(result["fields"]["callerLocation"], "Talisay City")
        self.assertEqual(lines[0], "Nitawag ang caller tungod sa Academic Problem.")
        self.assertIn("dili makatulog og tarong", lines[1])
        self.assertIn("dili makaginhawa og tarong", lines[1])
        self.assertIn("mobuto ang dughan", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertIn("Referred to Guidance Counselors", categories)
        self.assertIn("Given Referrals", categories)
        self.assertIn("Refused Referrals", categories)
        self.assertIn("Psychoeducation", categories)

    def test_summarizes_anonymous_work_burnout_with_passive_si(self):
        text = (
            "Caller:\n"
            "Ayaw lang ko pangayoi og name palihug... maulaw ko. 25 na ko, "
            "diri ko sa Davao nag-work karon. Single ko, ako ra usa diri sa "
            "akong apartment. Gikan ko nag-work, pag-abot nako sa kwarto, "
            "ni-breakdown na lang ko. Murag mobuto akong dughan. Sige lang "
            "kog trabaho, wa gihapoy asenso. Puno na kaayo ko. Di na nako "
            "ma-control akong paghilak. Nagkurog akong mga kamot. Naglisod "
            "kog ginhawa. Permi baya ko kulbaan inig mata nako. Karon lang "
            "gyud, naka-huna-huna ko kung mawala na lang ko kalit para "
            "muhunong na ang kasakit. Mura kog mo-give up na. Pero "
            "mahadlok man ko mamatay. Gusto lang ko og peace of mind.\n\n"
            "Responder:\n"
            "Valid na imong gibati. Mag-breathing exercise ta. Naa tay mga "
            "professional counselors sa Davao. Gusto nimo i-share nako "
            "ilang contact details?\n"
        )

        result = analyze(text, risk_assessment="Medium Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "N/A")
        self.assertEqual(result["fields"]["callerAge"], 25)
        self.assertEqual(result["fields"]["callerGender"], "N/A")
        self.assertEqual(result["fields"]["callerStatus"], "Single")
        self.assertEqual(result["fields"]["callerLocation"], "N/A")
        self.assertEqual(lines[0], "Nitawag ang caller tungod sa Burnout.")
        self.assertIn("naglaom nga dili na momata", lines[1])
        self.assertIn("wala na siyay paglaom", lines[1])
        self.assertIn("dili makaginhawa og tarong", lines[1])
        self.assertIn("mobuto ang dughan", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertNotIn("Work/Employment Problem", result["summary_bisaya"])
        self.assertIn("Given Referrals", categories)
        self.assertIn("Psychoeducation", categories)

    def test_summarizes_family_financial_burden_without_si(self):
        text = (
            "Caller:\n"
            "Hello... mangayo unta kog advice. Murag gikapoy na man gud ko "
            "pag-ayo, nangita lang kog mapahungawan. Sa balay namo, feel "
            "nako ako nalang pirme ang gina-asahan sa tanan. 32 na ko. Naa "
            "ko sa Cebu City ron. Single pa ko, maong sa akoa tanan "
            "gi-salig ang pagbuhi sa akong mga manghud ug ginikanan. Tulo "
            "mi ka magsuon. Ako ang kinamanghuran pero ako ang nagtrabaho. "
            "Ang akong duha ka magulang naay mga pamilya pero gapangayo "
            "gihapon nako. Akong mama ug papa, ako pa gyud ang mo-provide "
            "sa ilang maintenance. Nag-chat napud akong igsoon kay "
            "mangutang daw para ipalit og gatas. Nagsagol akong kalagot ug "
            "kaluoy. Sige ra kog hilak inig gabii. Usahay maka-feel ko ug "
            "kasuko nila, pero ma-guilty man sad ko masuko kay pamilya gud "
            "nako. Kapoy na kaayo akong utok nga sige ra kog huna-huna asa "
            "ko mokuha og kwarta. Wala man hinuon koy plano magpakamatay. "
            "Matulog na lang guro ko. Bug-at kaayo akong dughan ganina pa.\n\n"
            "Responder:\n"
            "Valid kaayo na imong gibati. Importante ang pag-set og "
            "boundaries. Mag-breathing exercise ta. Naa tay partner "
            "psychologists nga nag-offer og counseling. I-text nako ang "
            "contact number ug link sa ilang online session.\n"
        )

        result = analyze(text, risk_assessment="Medium Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "N/A")
        self.assertEqual(result["fields"]["callerAge"], 32)
        self.assertEqual(result["fields"]["callerGender"], "N/A")
        self.assertEqual(result["fields"]["callerStatus"], "Single")
        self.assertEqual(result["fields"]["callerLocation"], "Cebu City")
        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Family Problem."
        )
        self.assertIn("grabeng kasuko", lines[1])
        self.assertIn("bug-at ang dughan", lines[1])
        self.assertIn("nagsige og hilak", lines[1])
        self.assertIn("makonsensya", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertIn("Given Referrals", categories)
        self.assertIn("Psychoeducation", categories)

    def test_summarizes_relationship_infidelity_without_si(self):
        text = (
            "Caller:\n"
            "Hello... pwede ko makig-estorya? Sakit kaayo akong gibati "
            "karon. Nag-away mi sa akong uyab. Murag mobuto na akong dughan. "
            "Ako si Jessa. 26 na ko. Naa ko sa Mandaue City nag-board. "
            "Oo, babaye ko. Nasakpan nako siya nga naay lain. Nakita nako "
            "sa iyang phone ang mga messages. Grabe kaayo akong trust niya "
            "kay 4 years na mi. Gi-confront nako siya ganina, unya nag-away "
            "mi hangtod ni-walk out siya. Naglibog akong utok. Sige ra kog "
            "hilak sukad ganina buntag. Nagkurog akong tibuok lawas sa "
            "kasuko ug kaguol. Wala pa ko nikaon. Gikapoy na kaayo ko. "
            "Wala man koy plano magpakamatay. Pero dili ko pasakit sa akong "
            "kaugalingon tungod niya.\n\n"
            "Responder:\n"
            "Valid kaayo na imong kasakit ug kalagot. Normal ra nang "
            "magkurog ug mawad-an og gana. Mag-breathing exercise ta. "
            "Naa ba kay close friend o pamilya nga pwede nimo matawagan?\n"
        )

        result = analyze(text, risk_assessment="Medium Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "Jessa")
        self.assertEqual(result["fields"]["callerAge"], 26)
        self.assertEqual(result["fields"]["callerGender"], "Female")
        self.assertEqual(result["fields"]["callerLocation"], "Mandaue City")
        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Relationship Problem."
        )
        self.assertIn("mobuto ang dughan", lines[1])
        self.assertIn("grabeng kasuko", lines[1])
        self.assertIn("nagsige og hilak", lines[1])
        self.assertIn("nagkurog ang lawas", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertNotIn("Interpersonal Conflict", result["summary_bisaya"])
        self.assertIn("Psychoeducation", categories)

    def test_summarizes_nurse_burnout_without_family_false_positive(self):
        text = (
            "Caller:\n"
            "Maulaw man ko mag-estorya sir pero di na gyud nako kaya. "
            "Murag nibuto na man gud akong dughan ron. Kapoy kaayo, sir. "
            "Lami lang gyud i-hilak tanan. Ako si Marie, sir. Babaye ko. "
            "Naa ra ko sa sulod sa akong sakyanan, diri sa parking lot sa "
            "among apartment sa Mandaue. Nurse man gud ko sir sa usa ka "
            "dako nga public hospital. Taga-adlaw, ako ang tig-atiman, "
            "ako ang tig-comfort sa mga pamilya nga namatyan o nasakitan. "
            "Pag-gawas nako sa hospital ganiha human sa akong shift, "
            "nikalit lang ko'g hilak. Gi-absorb nako tanang sakit sa ubang "
            "tawo, unya karon kay empty na kaayo ko. Wala nakoy ihatag. "
            "Nagkurog ko diri sulod sa sakyanan. Naghuot akong dughan sir. "
            "Nagsakit akong ulo sige'g hilak unya murag numb ug bugnaw "
            "akong mga kamot. Wala man sir. Hadlok ko anang pasakitan ang "
            "kaugalingon. Gusto lang ko og break.\n\n"
            "Responder:\n"
            "Dili ka impostor, Marie. Tao ra pud ka. Dungan ta'g ginhawa "
            "kadiyot. Inhale... exhale. Valid na imong gibati. Sa hospital "
            "ninyo, duna ba moy support system o psychologist para sa mga "
            "staff? Importante nga ma-debrief mo. Deserve nimo mopahuway.\n"
        )

        result = analyze(text, risk_assessment="Medium Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "Marie")
        self.assertEqual(result["fields"]["callerGender"], "Female")
        self.assertEqual(result["fields"]["callerLocation"], "Mandaue City")
        self.assertEqual(lines[0], "Nitawag ang caller tungod sa Burnout.")
        self.assertIn("mobuto ang dughan", lines[1])
        self.assertIn("nagsige og hilak", lines[1])
        self.assertIn("empty ang pamati", lines[1])
        self.assertIn("nagkurog ang lawas", lines[1])
        self.assertNotIn("Family Problem", result["summary_bisaya"])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertIn("Given Referrals", categories)
        self.assertIn("Psychoeducation", categories)

    def test_anonymous_mood_swings_referral(self):
        text = (
            "Caller:\n"
            "Uhm, hello. Nangita ko ug doctor. Dugay na ni nako gi-feel. "
            "Naa ko sa Lapu-Lapu City. Pwede dili lang nako i-sulti akong "
            "pangalan? Gusto lang ko mag-anonymous. Usahay kalit lang ko "
            "ma-down kaayo, grabe nga kaguol. Ig sunod adlaw hyper kaayo "
            "ko, dili ko katulog kay daghan kaayog huna-huna nga paspas "
            "kaayo. Kapoy kaayo emotionally. Makulbaan ko usahay. Sapoton "
            "ko kalit. Dili man ko gusto mamatay.\n\n"
            "Responder:\n"
            "Naa tay psychiatrist ug partner clinic nga nag-offer og "
            "psychiatric assessment. Pwede tika tagaan ug contact details. "
            "Valid na imong gibati ug ma-manage ang symptoms.\n"
        )

        result = analyze(text, risk_assessment="Medium Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "N/A")
        self.assertEqual(result["fields"]["callerAge"], "N/A")
        self.assertEqual(result["fields"]["callerGender"], "N/A")
        self.assertEqual(result["fields"]["callerLocation"], "Lapu-Lapu City")
        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Bipolar and OCD."
        )
        self.assertIn("kalit nga pagka-down ug kadasig", lines[1])
        self.assertIn("dili makatulog og tarong", lines[1])
        self.assertIn("gikulbaan", lines[1])
        self.assertIn("dali masuko", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertIn("Given Referrals", categories)
        self.assertIn("Psychoeducation", categories)

    def test_summarizes_anonymous_depression_with_passive_si(self):
        text = (
            "Caller:\n"
            "Hello sir. Secret ra ni atong estorya diri noh?\n\n"
            "Responder:\n"
            "Oo, confidential ang tanan.\n\n"
            "Caller:\n"
            "Gusto lang unta ko nga anonymous sir. Ayaw lang ko pangutan-a sa "
            "akong ngalan o edad o taga asa ko.\n\n"
            "Responder:\n"
            "Pwede ra tika tawgon nga 'te'.\n\n"
            "Caller:\n"
            "Tawga lang ko'g 'te', sir. Usa man ko ka inahan. Ambot sir, wa "
            "ko kabalo unsa ang nahitabo nako. Kumpleto man unta akong "
            "pamilya, pero pagmata nako buntag, gusto ra ko mag-higda. Wala "
            "koy gana mulihok. Kalit lang motulo akong luha. Gikapoy na akong "
            "bana nako. Na-guilty sad ko kay wa nako naatiman akong mga anak.\n\n"
            "Responder:\n"
            "Kasabot ko sa imong gibati.\n\n"
            "Caller:\n"
            "Wala gyud koy gana mokaon sir. Magmata ra sad akong diwa hantod "
            "kadlawon. Manakit akong ulo. Numb kaayo akong feeling, murag wa "
            "na koy ma-feel nga kalipay.\n\n"
            "Responder:\n"
            "Naka-huna-huna ba ka nga mawala na lang ka?\n\n"
            "Caller:\n"
            "Usahay mag-ampo ko nga dili na lang unta ko makamata. Pero wala "
            "man ko nagplano nga hikugon akong kaugalingon. Lami lang gyud "
            "mopahuway na forever.\n\n"
            "Responder:\n"
            "Ang imong gipamati kay usa ka kondisyon, dili lang inarte. "
            "Valid nang imong gibati. Kinahanglan og tabang sa psychologist "
            "o psychiatrist. Pwede tika tagaan og number sa Vicente Sotto, "
            "naa silay free consultation.\n\n"
            "Caller:\n"
            "Ayaw lang sa sir. Dili ko gusto mogawas sa balay ron.\n"
        )

        result = analyze(text)
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "N/A")
        self.assertEqual(result["fields"]["callerAge"], "N/A")
        self.assertEqual(result["fields"]["callerGender"], "Female")
        self.assertEqual(result["fields"]["callerStatus"], "Married")
        self.assertEqual(result["fields"]["callerLocation"], "N/A")
        self.assertEqual(lines[0], "Nitawag ang caller tungod sa Depression.")
        self.assertIn("naglaom nga dili na momata", lines[1])
        self.assertIn("dili makatulog og tarong", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertIn("Given Referrals", categories)
        self.assertIn("Refused Referrals", categories)
        self.assertIn("Psychoeducation", categories)

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
        payload = response.json()
        summary = payload["summary"]
        self.assertIn("due to Academic Problem.", summary)
        self.assertIn("In the risk assessment, high risk.", summary)
        self.assertIn("tungod sa Academic Problem.", payload["summary_bisaya"])

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
