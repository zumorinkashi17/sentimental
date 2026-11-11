import json
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse

from .nlp import analyze
from .nlp.rules import extract_caller_text
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

    def test_summarizes_bipolar_relapse_without_name_false_positive(self):
        text = (
            "Caller:\n"
            "Pasensya ma'am, di gyud nako mapugngan! Kapoy na kaayo ko pero "
            "di ko katulog! Wag na ang pangalan ma'am, tawga lang kog 'friend'. "
            "28 ko karon. Single ko. Na-diagnose ko'g Bipolar II sauna, naay "
            "sagol OCD. Niundang ko'g inom last month. Tulo na ka adlaw wala "
            "koy tulog. Sige ko'g panghugas sa akong kamot hangtod nag-dugo. "
            "Galumba-lumba akong huna-huna. Naka-hunahuna ko muinom ug daghang "
            "tambal para matulog forever. Pero nahadlok ko.\n\n"
            "Responder:\n"
            "Pwede ka mo-contact sa imong psychiatrist. Mag-grounding ta.\n"
        )

        result = analyze(text, risk_assessment="High Risk")
        lines = result["summary_bisaya"].splitlines()

        self.assertEqual(result["fields"]["callerName"], "N/A")
        self.assertEqual(result["fields"]["callerAge"], 28)
        self.assertEqual(result["fields"]["callerStatus"], "Single")
        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Bipolar and OCD."
        )
        self.assertIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertIn("racing thoughts", lines[1])
        self.assertNotIn("Pasensya", result["summary"])
        self.assertNotIn("friend", result["summary"])

    def test_summarizes_cyberbullying_with_self_harm_and_anonymity(self):
        text = (
            "Caller:\n"
            "Ang mga tawo sa Facebook sige silag yaga-yaga nako. "
            "Di lang ko musulti sa akong name ma'am. 16 pa ko. Bayot ko. "
            "Gi-screenshot akong private post unya gi-post sa school confessions "
            "page. Nag-kurog akong tibuok lawas. Gikulbaan ko. Nagsakit akong "
            "dughan. Nakakuha kog blade ganina. Gusto ko garasan akong bukton. "
            "Pero nahadlok ko ma'am.\n\n"
            "Responder:\n"
            "Pwede ka mo-adto sa guidance counselor. Mag-breathing exercise ta.\n"
        )

        result = analyze(text, risk_assessment="High Risk")
        lines = result["summary_bisaya"].splitlines()

        self.assertEqual(result["fields"]["callerName"], "N/A")
        self.assertEqual(result["fields"]["callerAge"], 16)
        self.assertEqual(result["fields"]["callerGender"], "LGBTQ+")
        self.assertEqual(lines[0], "Nitawag ang caller tungod sa Cyberbullying.")
        self.assertIn("adunay mga hunahuna sa pagpasakit sa kaugalingon", lines[1])
        self.assertNotIn("Facebook", result["summary"])

    def test_summarizes_work_crisis_with_passive_escape(self):
        text = (
            "Caller:\n"
            "Ako diay si Carlo. Sige kog hilak. Nakadawat ko ug bad news gikan "
            "sa work, basin ma-end akong contract. Nag-away mi sa akong partner. "
            "Murag empty ug kapoy. Paspas akong heartbeat. Bug-at akong dughan. "
            "Tulo ka gabii na putol-putol akong tulog. Wala pa ko mokaon. "
            "Male ko. Naa ko sa Consolacion. Nakahuna-huna ko nga mas maayo "
            "siguro kung mawala lang ko kadali. Pero wala ko nagplano nga "
            "pasakitan akong kaugalingon.\n\n"
            "Responder:\n"
            "Pwede tika ma-refer sa mental health professional. "
            "Mag-breathing exercise ta.\n"
        )

        result = analyze(text, risk_assessment="Medium Risk")
        lines = result["summary_bisaya"].splitlines()

        self.assertEqual(result["fields"]["callerName"], "Carlo")
        self.assertEqual(result["fields"]["callerGender"], "Male")
        self.assertEqual(result["fields"]["callerLocation"], "Consolacion")
        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Work/Employment Problem."
        )
        self.assertIn("gusto lang nga mawala", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertNotIn("feeling alone", result["summary"])

    def test_summarizes_business_loss_as_financial_problem(self):
        text = (
            "Caller:\n"
            "Gio lang akong pangalan. Pwede dili lang nako isulti kung asa ko. "
            "30 na ko. Single ra ko. Nag-close ang akong gamay nga negosyo. "
            "Gibuhos nako tanan nakong savings. Zero na ko. Naulaw ko sa akong "
            "pamilya. Nagsige kog hilak. Wala koy kusog. Naa koy na-feel nga "
            "lami na lang matulog ug di na momata. Pero nahadlok ko mamatay. "
            "Wala ko nagplano.\n\n"
            "Responder:\n"
            "Normal ra nang imong gibati. Mag-breathing exercise ta.\n"
        )

        result = analyze(text, risk_assessment="Medium Risk")
        lines = result["summary_bisaya"].splitlines()

        self.assertEqual(result["fields"]["callerName"], "Gio")
        self.assertEqual(result["fields"]["callerAge"], 30)
        self.assertEqual(result["fields"]["callerStatus"], "Single")
        self.assertEqual(result["fields"]["callerLocation"], "N/A")
        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Financial Problem."
        )
        self.assertIn("naglaom nga dili na momata", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])

    def test_summarizes_bipolar_mood_swings_without_false_active_si(self):
        text = (
            "Caller:\n"
            "Ako diay si Leah. Pwede dili lang nako i-share akong location. "
            "26 na ko. Single. Female ko. Grabe akong mood swings. Hyper kaayo "
            "ko nga dili ko matulog for three days. Unya ma-depress ko og "
            "maayo. Wala koy gana mokaon. Blangko akong utok. Sige kog hilak. "
            "Wala koy kalipay. Mo-cross sa akong huna-huna panagsa pero dili "
            "nako buhaton. Nahadlok ko mo-suicide. Gusto ko mamaayo.\n\n"
            "Responder:\n"
            "Chemical imbalance ni, dili ka nag-inarte. Pwede ka moadto sa "
            "psychiatrist. Naa mi referral nga i-text. Mag-breathing exercise ta.\n"
        )

        result = analyze(text, risk_assessment="Medium Risk")
        lines = result["summary_bisaya"].splitlines()

        self.assertEqual(result["fields"]["callerName"], "Leah")
        self.assertEqual(result["fields"]["callerAge"], 26)
        self.assertEqual(result["fields"]["callerGender"], "Female")
        self.assertEqual(result["fields"]["callerStatus"], "Single")
        self.assertEqual(result["fields"]["callerLocation"], "N/A")
        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Bipolar and OCD."
        )
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertIn(
            "Psychoeducation",
            result["field_meta"]["intervention"]["categories"],
        )

    def test_summarizes_anger_without_false_self_harm_ideation(self):
        text = (
            "Caller:\n"
            "Tawga lang ko og Jen. Pwede dili lang nako isulti ang location. "
            "23 na ko. Single. Grabe akong kalagot sa akong kauban sa balay. "
            "Nanghulam siya og 5k unya gidaot ko niya sa among barkada. "
            "Sige kog palpitate. Dili ko katulog og tarong kay sige kog "
            "overthink. Kapoy akong utok. Gusto nako siya sagpaon pero "
            "nagpugong ko. Pasakitan akong kaugalingon, wala man. Dili nako na "
            "buhaton.\n\n"
            "Responder:\n"
            "Valid imong kasuko. Mag-breathing exercise ta. Pwede nimo siya "
            "ipa-barangay.\n"
        )

        result = analyze(text, risk_assessment="Low Risk")
        lines = result["summary_bisaya"].splitlines()

        self.assertEqual(result["fields"]["callerName"], "Jen")
        self.assertEqual(result["fields"]["callerAge"], 23)
        self.assertEqual(result["fields"]["callerStatus"], "Single")
        self.assertEqual(result["fields"]["callerLocation"], "N/A")
        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Anger Management Issue."
        )
        self.assertIn("grabeng kasuko", lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpasakit sa kaugalingon", lines[1])
        self.assertIn(
            "Psychoeducation",
            result["field_meta"]["intervention"]["categories"],
        )

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

    def test_summarizes_academic_failure_with_active_si_and_guidance_referral(self):
        text = (
            "Maayong adlaw, Tawag Paglaum. Ako si Anna. Naa ba koy matabang "
            "nimo karon?\n\n"
            "Hi miss... uhm, nag-hesitate ko manawag ba pero gusto lang ko "
            "naay mapahungawan karon. Dili na gyud nako kaya.\n\n"
            "Okay ra kaayo na. Sakto imong gibuhat nga nitawag ka. Diri sa "
            "Tawag Paglaum, safe kaayo ka mag-share. Unsa man diay ang "
            "naghatag nimo og kabug-at karon?\n\n"
            "Murag ma-buang na gyud ko miss. Sige ra kog hilak since pagmata "
            "nako ganiha. Wala ko kabalo unsaon nako pag-atubang ani.\n\n"
            "Sige, paminawon tika. Para mas comfortable atong storya, pwede "
            "ba ko makabalo unsay imong pangalan?\n\n"
            "Tawga lang ko og Kim.\n\n"
            "Hi Kim. Pila na diay imong edad ug taga-asa ka, para lang "
            "magka-ila ta og tarong?\n\n"
            "20 pa ko. Taga-Talisay City, miss.\n\n"
            "Salamat, Kim. Sultihi daw ko, unsa may nahitabo nga nagsige man "
            "ka og hilak ganiha pa?\n\n"
            "Ni-gawas man gud ang mga grades namo sa portal ganiha buntag. "
            "Hagbong ko sa akong duha ka major subjects. Karon pa ko "
            "na-hagbong sa akong tibuok kinabuhi miss. Nursing man gud akong "
            "gikuha. Dili na ko kabalo unsaon pag-atubang sa akong parents, "
            "especially sa akong papa.\n\n"
            "Grabe gyud na nga shock, Kim, labi na nga first time ni nimo "
            "nasinati unya major subjects pa gyud. Bug-at gyud na sa "
            "pagbati.\n\n"
            "Oo, miss. Strict kaayo akong papa. Ang expectation nila kay "
            "maka-graduate ko with honors unya maka-work dayon abroad para "
            "makatabang sa mga manghod. Ako pay panganay. Kung makabalo sila "
            "ani, ipaundang na gyud ko nila ug skwela o kaha palayason ko sa "
            "balay.\n\n"
            "Nakasabot ko sa kahadlok nimo karon, Kim. Lahi gyud ang pressure "
            "basta panganay unya dako ang expectations. Aside sa paghilak, "
            "unsa pa may imong na-feel karon sa imong lawas or huna-huna?\n\n"
            "Nagkurog akong kamot ganiha pa, miss. Ug nagsuka ko "
            "pagkahibalo nako sa grades. Murag di nako makaginhawa sa "
            "kakulba every time mahinumdom ko nga mouli na akong papa unyang "
            "hapon. Wala pa koy tulog tarong kay nag-cramming man ko gabii "
            "naghimo ug projects, unya pag-open nako sa portal mao to akong "
            "nakita.\n\n"
            "Ingon ka nga grabe imong kakulba unya murag di ka "
            "makaginhawa. Sa kani nga sitwasyon nga gibati nimo og grabeng "
            "kahadlok nga mouli imong papa, nakahunahuna ba ka og buhaton "
            "nga makapasakit sa imong kaugalingon?\n\n"
            "Nakahunahuna ko nga molayas na lang miss... or moinom og "
            "daghang tambal para makatulog ug di na momata kay di ko gusto "
            "maka-dungog sa kasaba ug kasakit. Pero nahadlok man pud ko "
            "buhaton.\n\n"
            "I appreciate your honesty, Kim. Importante kaayo nga nisulti ka "
            "nako ana. Ang kahadlok nga imong gibati kay nagpakita nga gusto "
            "pa nimo mangita og laing paagi nga masulbad ni, gawas sa "
            "pagpasakit sa imong kaugalingon. It takes courage to admit "
            "that.\n\n"
            "Right now, dako kaayo ang anxiety nga imong na-feel ug "
            "nag-panic imong lawas. Gusto nako nga tabangan tika ma-ground "
            "imong kaugalingon. Pwede ba ta mag-dungan og focus sa atong "
            "pagginhawa kadiyot?\n\n"
            "S-sige miss.\n\n"
            "Okay. I-relax imong abaga. Ginhawa og lalom sa ilong for 4 "
            "seconds... unya pag-exhale slowly sa baba. (pause) Usa pa, "
            "inhale in... exhale out.\n\n"
            "(breathing deeply) ...\n\n"
            "Good. Gusto lang ko mo-remind nimo, Kim, nga ang imohang worth "
            "as a person ug as an anak kay wala nag-depende sa duha ka "
            "grades. Kahibalo ko nga bug-at ang expectation sa parents, pero "
            "failing a subject doesn't mean failure ka sa kinabuhi.\n\n"
            "Dili lang gyud ko ready nga mo-face niya ron miss. Basig "
            "kulatahon ko.\n\n"
            "Valid na nga kahadlok. Naa ba kay close friend, or kapamilya "
            "like tita or tito, nga pwede nimo adtoan o maestorya karon "
            "before nimo atubangon imong papa? O kaha sa school ninyo, "
            "na-try ba nimo ug duol ang guidance counselor para ma-discuss "
            "ang options sa imong nabagsak nga subjects?\n\n"
            "Naa koy tita nga buotan kaayo, igsoon sa akong mama, ug close "
            "pud sila ni papa. Pwede ko adto sa ilaha mag-stay karong hapon, "
            "basin matabangan ko niya og sulti. Sa guidance counselor, wala "
            "pa miss kay na-shock pa lagi ko.\n\n"
            "That's a very good and safe plan, Kim. Adto sa imong tita para "
            "naay mu-support nimo, labi na kung nabalaka ka sa imong safety. "
            "And then next week, pag medyo kalma na ang tanan, pwede nimo "
            "adtoan ang guidance office para makabalo ka unsa ang process sa "
            "retake sa imong subjects.\n\n"
            "Sige miss. Mo-text ko sa akong tita karon dayon nga mo-adto ko. "
            "Medyo ni-kalma na akong kurog. Salamat kay naminaw ka.\n\n"
            "Nalipay ko nakadungog ana, Kim. Hinay-hinay lang usa. Pag-inom "
            "og tubig, and make sure nga mo-kaon ka. And remember, naa ra "
            "ang Tawag Paglaum if ever kailangan nimo og kaestorya usab.\n\n"
            "Thank you so much, miss Anna. Dako kay ni og tabang.\n\n"
            "Amping kanunay, Kim. Take care. Bye."
        )

        result = analyze(text, risk_assessment="High Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]
        caller_text = extract_caller_text(text)

        self.assertEqual(result["fields"]["callerName"], "Kim")
        self.assertEqual(result["fields"]["callerAge"], 20)
        self.assertEqual(result["fields"]["callerGender"], "N/A")
        self.assertEqual(result["fields"]["callerStatus"], "N/A")
        self.assertEqual(result["fields"]["callerLocation"], "Talisay City")
        self.assertEqual(
            categories,
            ["Referred to Guidance Counselors", "Psychoeducation"],
        )
        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Academic Problem."
        )
        for phrase in (
            "adunay mga hunahuna sa pagpakamatay",
            "gikulbaan",
            "nagsige og hilak",
            "nagkurog ang kamot",
        ):
            self.assertIn(phrase, lines[1])
        self.assertNotIn("gisagpa ug gitukmod", lines[1])
        self.assertEqual(lines[2], "Sa risk assessment, high risk.")
        self.assertIn("nag-refer sa guidance counselor", lines[3])
        self.assertIn("psychoeducation", lines[3])
        self.assertNotIn("Right now, dako kaayo", caller_text)
        self.assertNotIn("Valid na nga kahadlok", caller_text)
        self.assertEqual(
            [(entity["label"], entity["text"]) for entity in result["entities"]],
            [
                ("NAME", "Kim"),
                ("AGE", "20"),
                ("LOCATION", "Talisay City"),
            ],
        )

    def test_handles_consecutive_responder_questions_and_panic_symptoms(self):
        text = """
Hello, Tawag Paglaum ni. Ako si Ana, usa ko sa mga responders diri. Kumusta man ka karon?

Hello... okay ra man siguro. Medyo lisod lang gyud akong gibati karon.

Sige, salamat nga nitawag ka. Unsa man ang nahitabo karon?

Murag dili na nako makontrol akong hunahuna. Sige kog overthink.

Kanus-a nimo unang nabantayan nga ing-ani na ka pirmi?

Mga pila na ka buwan. Usahay wala koy problema, pero kalit lang ko makulbaan.

Bisan wala kay klarong problema, mobati gihapon ka og kahadlok?

Oo. Murag naay something bad nga mahitabo.

Lisod siguro nang naa kay kahadlok.

Mao gyud. Abi nako OA ra ko.

Dili nato kinahanglan tawgon dayon nga OA imong gibati. Importante nga nakabantay ka nga nakaapekto na siya nimo.

By the way, unsa diay akong itawag nimo?

Jessa.

Hi, Jessa. Pila na imong edad karon?

Twenty-four ko.

Salamat, Jessa. Asa ka dapit karon?

Sa Lapu-Lapu ko nagpuyo.

Okay. Unsa imong gender?

Female ko.

Sige. Single pa ka karon?

Oo, single pa.

Unsa imong gibati sa imong lawas kung kusog ang kakulba?

Mupaspas akong heartbeat. Mangurog akong kamot usahay, unya murag dili ko kapugngan akong breathing. Mura kog kulang sa hangin bisan kabalo ko nga nagginhawa man ko.

Once magsugod akong heart nga paspas, mahadlok na pud ko nga basin atakehon ko.

Kumusta imong tulog?

Dili maayo. Usahay alas dos o alas tres na ko makatulog. Pagkabuntag, murag wala koy energy.

Nakaabot ba ka sa punto nga nakahunahuna ka nga pasakitan imong kaugalingon?

Wala. Wala ko naghunahuna nga pasakitan akong kaugalingon.

Normal ra nga makulbaan ka kung first time. Valid na imong gibati.

Kung open ka, pwede tika ma-refer sa psychologist.

Actually, willing ko.
"""

        result = analyze(text, risk_assessment="Low Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]
        caller_text = extract_caller_text(text)

        self.assertEqual(result["fields"]["callerName"], "Jessa")
        self.assertEqual(result["fields"]["callerAge"], 24)
        self.assertEqual(result["fields"]["callerGender"], "Female")
        self.assertEqual(result["fields"]["callerStatus"], "Single")
        self.assertEqual(result["fields"]["callerLocation"], "Lapu-Lapu City")
        self.assertEqual(categories, ["Given Referrals", "Psychoeducation"])
        self.assertEqual(lines[0], "Nitawag ang caller tungod sa Panic Attack.")
        for phrase in (
            "gikulbaan",
            "dili makaginhawa og tarong",
            "dili makatulog og tarong",
            "nagkurog ang kamot",
        ):
            self.assertIn(phrase, lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertNotIn("By the way, unsa diay akong itawag nimo?", caller_text)
        self.assertNotIn("Normal ra nga makulbaan ka", caller_text)
        self.assertEqual(
            [
                (entity["label"], entity["text"])
                for entity in result["entities"]
                if entity["label"] in {"NAME", "AGE"}
            ],
            [("NAME", "Jessa"), ("AGE", "Twenty-four")],
        )

    def test_handles_depression_with_passive_si_and_conditional_er_plan(self):
        text = """
Maayong gabii, nakaabot ka sa Tawag Paglaum. Ako si Carlo. Pwede ra kaayo ka mag-share diri sa unsay naa sa imong hunahuna. Unsay nahitabo karon nga nakapadasig nimo nga motawag?


Hi... dugay na gyud ko naghunahuna kung motawag ba ko. Karon lang gyud ko ni-decide kay murag dili na nako kaya nga ako ra.


Okay. Salamat nga nakahimo ka og step nga motawag. Dili ka kinahanglan magdali sa pag-storya. Unsa man gyud ang pinakabug-at para nimo karon?


Murag nawala na akong gana sa tanan. Sauna active kaayo ko, sige kog gawas, makigkita sa friends. Karon ganahan ra ko magpundo sa kwarto.


Dako gyud og kausaban kung gikan sa pagka-active, nahimo na lang kang ganahan mag-inusara. Dugay na ni nga imong gibati?


Mga upat ka bulan na siguro. At first abi nako kapoy lang ko tungod sa work. Pero niabot sa point nga bisan weekends, dili na ko ganahan mobangon.


Unsa imong gibuhat kasagaran kung naa ka ana nga feeling?


Matulog ko. Or maghigda ra ko, magtan-aw sa ceiling. Usahay mag-phone ko for hours pero wala gyud koy ma-feel nga enjoyment.


Pwede ko makabalo sa imong name?


Mark.


Hi, Mark. Pila na ka tuig?


Twenty-seven.


Asa ka nagpuyo karon, Mark?


Sa Mandaue ko nagpuyo.


Ug married na ka or single?


Married ko. Duha mi kabuok sa akong wife.


Salamat sa pag-share. Unsay gender nimo, Mark?


Lalaki ko.


Naa bay nahitabo mga upat ka bulan ang milabay nga tingali naka-trigger sa imong gibati?


Oo. Na-promote ko unta sa work pero wala nako nakuha. Ang akong kauban nga mas bag-o pa nako, siya ang napili. Dili man unta ko suko niya, pero murag na-question gyud nako akong kaugalingon.


Murag nakaapekto siya sa imong pagtan-aw sa imong kaugalingon.


Oo. Sige kog compare. Makaingon ko, "Unsay kulang nako?" Unya pagkahuman ato, nagsunod-sunod na ang problema. Naa pud mi'y financial issues sa balay.


Nakasulti ba ka sa imong wife bahin sa imong gibati?


Gamaya ra. Dili ko ganahan nga ma-stress pud siya. Kung mangutana siya kung okay ra ba ko, moingon ra ko nga kapoy ko.


So kadaghanan sa imong gibati, imo rang gitago.


Oo. Kay lalaki man ko, unya murag expected nga dapat kabalo ko unsaon pag-handle sa problema.


Pero sa sulod nimo, unsa gyud imong kasinatian?


Murag empty. Wala koy excitement. Bisan akong mga anak nga ganahan kaayo ko sauna makigdula, usahay makakita ko nila pero wala koy energy nga mosabay.


Nabantayan nimo nga naapektuhan na pud imong trabaho?


Oo. Maglisod kog focus. Naay times nga magtan-aw ra ko sa computer unya wala gyud ko kasabot sa akong gibasa. Naa pud koy mga tasks nga akong ginapalangan.


Kumusta imong tulog ug pagkaon these past few weeks?


Ang tulog kay gubot. Usahay sayo ko matulog pero mata ko mga alas tres sa buntag. Then maghunahuna na pud ko hangtod buntag. Sa pagkaon, usahay usa ra ko ka meal sa tibuok adlaw kung busy ko.


Unsa kasagaran imong gihunahuna kung mata ka sa kadlawon?


Nga wala ko'y pulos. Nga basin dili gyud ko maayo sa akong trabaho. Usahay mahunahuna nako nga mas maayo pa siguro kung dili na lang ko mahimong burden sa akong family.


Bug-at kaayo nang mga hunahuna. Kung moabot na ka ana nga point, unsa imong gibati emotionally?


Maka-drain. Usahay mohilak ko nga ako ra. Dili ko ganahan makita sa akong mga anak.


Mark, mangutana ko nimo direkta kay importante nga masiguro nato imong safety. Kung moabot ka sa thought nga burden ka sa imong family, nakaabot ba ka sa punto nga nakahunahuna ka nga pasakitan imong kaugalingon o tapuson imong kinabuhi?


Nahunahuna nako usahay nga basin mas maayo kung mawala na lang ko. Pero wala koy plano nga pasakitan akong kaugalingon.


Salamat sa imong pagkamatinud-anon. Karon mismo, naa ba kay gibati nga mahimo nimong pasakitan imong kaugalingon?


Wala. Karon dili. Gusto ra gyud ko makagawas ani nga feeling.


Okay. Importante nga karon safe ka. Kung mosamot ang thoughts ug mobati ka nga basin dili na nimo mapugngan ang imong kaugalingon, ayaw pag-inusara—duol dayon sa imong wife o sa laing tawo nga imong kasaligan ug pangayo og immediate nga tabang.


Sige. Actually, basin kinahanglan na gyud nako mosulti sa akong wife.


Sa imong gi-share, murag dugay na nimo ning gidala nga ikaw ra. Pwede nato sugdan sa gamay nga step: dili kinahanglan nimo masulbad tanan karong gabhiona. Ang importante, naa kay usa ka tawo nga makasabot kung unsa gyud imong giagian.


Lisod siya buhaton pero basin mas maayo kaysa sige ra kog tago.


Yes. Ug karon, suwayi sa paghinay-hinay og ginhawa. Dili para mawala dayon ang problema, pero para makatabang nga ma-settle gamay imong lawas samtang nag-storya ta.


Okay.


Inhale hinay... unya exhale. Ayaw pugsa. Focus lang sa imong breathing for a few moments.


Okay... medyo mas relaxed ko gamay.


Maayo. Ug gusto pud nako nga mahibaloan nimo nga ang imong gibati dili kinahanglan nga ikaw ra ang mosulbad. Ang pagkawala sa gana, problema sa tulog, lisod nga concentration, ug dugay nga kabug-at nga imong gi-experience kay mga butang nga angay seryosohon ug maistoryahan sa professional.


Kung okay ra nimo, pwede tika ma-refer sa psychologist para mas ma-assess ang imong gibati ug makadawat ka og support nga angay sa imong situation.


Oo, willing ko. Actually, gusto na gyud nako nga naay makatabang nako.


Maayo. Pwede pud nimo isulti sa imong wife karong gabhiona nga dili ka okay lately ug gusto ka nga ubanan ka niya sa pagpangita og professional support.


Sige. I think mao na akong buhaton. Dili na nako gusto nga ako ra.


And if ever moabot ka sa point nga dili na safe nga ikaw ra, pangayo dayon og immediate help gikan sa imong wife o trusted person ug adto sa emergency service o nearest emergency room.


Okay. Sabton nako.


Before ta mag-end, Mark, gusto lang nako ma-check—safe pa ba ka karon, ug naa ba kay plan nga buhaton after sa atong conversation?


Safe ko. Tawagan nako akong wife unya istoryahan nako siya. Ug mangita gyud ko og psychologist.


Maayo nga naa kay klaro nga next step. Dili kinahanglan nga ma-fix nimo tanan dayon. Usa-usa lang. Ug salamat nga nakahimo ka og share karong gabhiona bisan lisod para nimo.


Salamat pud. Murag dugay na gyud ko wala nakaingon sa akong gibati.
"""

        result = analyze(text, risk_assessment="Low Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "Mark")
        self.assertEqual(result["fields"]["callerAge"], 27)
        self.assertEqual(result["fields"]["callerGender"], "Male")
        self.assertEqual(result["fields"]["callerStatus"], "Married")
        self.assertEqual(result["fields"]["callerLocation"], "Mandaue City")
        self.assertEqual(categories, ["Given Referrals", "Psychoeducation"])
        self.assertEqual(lines[0], "Nitawag ang caller tungod sa Depression.")
        for phrase in (
            "naglaom nga dili na momata",
            "wala nay kalipay",
            "dili makatulog og tarong",
            "empty ang pamati",
        ):
            self.assertIn(phrase, lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertEqual(lines[2], "Sa risk assessment, low risk.")

    def test_handles_overwhelm_with_work_trigger_and_passive_escape(self):
        text = """
Maayong hapon. Tawag Paglaum ni. Ako si Nica, responder karon. Kumusta ka? Unsay nahitabo nga nakaingon ka nga motawag ka today?

Hi, ma'am... dili ko sure asa magsugod. Murag kalit lang gyud ko na-overwhelm. Since this morning sige na kog hilak.

Okay ra. Pwede ra gyud ka magsugod bisan asa. Unsa man ang pinakabug-at sa imong gibati karon?

Murag tanan. Akong work, akong family, mga problema nga wala pa nako na-solve. Murag niabot ko sa point nga dili na gyud ko kabalo unsa akong unahon.

Murag daghan kaayo og nagsabay-sabay nga imong gidala.

Oo. Kasagaran kaya ra nako man. Pero karon murag kalit lang ko na-collapse emotionally. Wala gani koy gana mobangon ganina.

Naa bay nahitabo karong mga adlawa nga murag naka-push sa imong emotions ngadto ana nga point?

Naay problema sa work. Gisaway ko sa akong supervisor about a mistake. Dili man gani siya dako nga mistake, pero after ato murag akong tanan nakong previous failures nibalik sa akong huna-huna.

So dili lang tong usa ka incident, pero murag nahimo siyang trigger sa daghan na nimong gipangdala daan.

Mao gyud. Then pag-abot nako sa balay, naa napud koy family issue. Murag wala gyud koy time nga makapahuway mentally.

Kasabot ko. Sometimes one difficult moment can make everything else feel heavier, especially kung kapoy na daan ka.

Mao. Mao pud tingali nga nitawag ko kay dili ko gusto nga magpadayon ko nga ako ra usa.

By the way, unsa imong pangalan? Unsay itawag nako nimo?

Camille.

Hi, Camille. Pila na imong edad?

29.

Asa ka nagpuyo karon?

Sa Lapu-Lapu City ko nagpuyo.

Okay. Unsa pud imong gender?

Babaye ko.

Salamat. Married ba ka or single?

Single pa ko.

Camille, unsa imong gibuhat pagkahuman nimo ma-receive ang feedback sa imong supervisor?

Nagpabilin ra ko sa akong desk. Niingon ko sa akong kaugalingon nga okay ra, pero internally grabe na akong ka-pressure. Pag-break nako, didto na ko nagsugod ug hilak.

Naa bay naka-notice sa imong ka-work nga dili ka okay?

Naay usa ka officemate nga nangutana kung okay ra ba ko. Niingon lang ko nga kapoy ko.

Ngano nga lisod para nimo isulti nga emotionally overwhelmed ka?

Dili ko ganahan nga luoyon ko. And naanad ko nga ako ang tig-handle sa akong problems. Murag embarrassing pud nga tungod lang sa usa ka mistake, ing-ani na dayon akong reaction.

Pero para nimo, feeling nimo nga mas dako na ang impact kaysa sa actual mistake.

Oo. Sige kog ingon sa akong kaugalingon nga incompetent ko. Basin dili gyud ko maayo sa akong work. Then maabot pa sa point nga mahuna-hunaan nako nga disappoint ko sa akong family.

Pirmi ba ni nga thought, or karon lang siya kusog?

Karon lang gyud siya grabe. Normally ma-stress ra ko, pero karon murag dili nako ma-stop akong thoughts.

Unsay mahitabo kung mosugod na sila?

Mag-imagine ko sa worst things. Basin mawala akong trabaho, basin maguba akong relationship with my family, basin wala gyud koy ma-achieve. Then makahilak na pud ko.

Karon, Camille, unsa gyud imong physical ug emotional feeling? Naa kay gibati nga tension or something similar?

Tight akong chest. Murag bug-at akong lawas. Sige pud kog sigh. And emotionally, murag empty ko after all the crying.

Kumusta imong sleep these past few nights?

Dili kaayo maayo. Around five hours lang. Magmata ko usahay in the middle of the night unya maghunahuna gihapon sa work.

Naa ba kay gana mokaon?

Dili kaayo. This morning kape ra akong nainom. Wala ko naka-breakfast.

Nakaapekto na ba ni sa imong normal routine?

Oo. Even akong usual chores, wala nako nabuhat. Ganahan ra ko magpabilin sa room.

Naa pa kay moments nga makaparelax ka or makapahappy gamay?

Akong dog usually. Pero karon gani, bisan ganahan ko makigdula niya, murag wala lang gyud koy energy.

Camille, mangutana ko ug direct nga question kay importante nga masiguro nato imong safety. Tungod kay ingon ka nga murag dili na nimo ma-stop imong thoughts, nakaabot ba ka sa point nga nakahunahuna ka nga dili na lang ka gusto mabuhi or nga pasakitan imong kaugalingon?

Naa koy moment ganina nga nakaingon ko, "Kung mawala lang unta ko kadali, dili na ko kinahanglan mag-atubang ani tanan." Pero wala ko naghunahuna unsaon pagpasakit sa akong kaugalingon.

Sige. Salamat nga gisulti nimo na honestly. Karon, naa ba kay intention nga pasakitan imong kaugalingon?

Wala, ma'am.

Naa ba kay plano nga buhaton kana karon or later?

Wala pud.

Safe ra ka karon diin ka?

Oo. Naa ra ko sa akong room, unya naa akong ate sa sala.

Maayo nga naa kay close nga person nearby. If mahimo, ayaw sa pag-inusara karong gabhiona while you're feeling this overwhelmed.

Sige. Pwede ra nako siya duolon.

Maayo. Importante nga naa kay someone nga pwede nimo maistoryahan while you're going through this.

Camille, at this moment, dili nato kinahanglan sulbaron tanan nimong problema. Murag overloaded na kaayo imong mind, so atong i-focus sa usa ka butang nga makatabang nimo makalma gamay.

Okay.

Try nato ug hinay nga breathing. Ibutang lang imong feet sa floor. Hinay nga inhale... unya hinay pud nga exhale. Ayaw pugsa nga mawala dayon ang emotion. Just give yourself a moment to slow down.

Sige... medyo lisod at first.

Okay ra. Another one. Hinay lang. Dili kinahanglan perfect.

Medyo ni-relax gamay akong shoulders.

Good. And karon, instead nga tan-awon nimo tanan nga problema as one big thing, unsa man ang pinakaduol nga kinahanglan nimong atubangon? Dili necessarily ang pinaka-dako, but the next manageable thing.

Siguro kinahanglan lang ko makauli sa normal nga state before ko maghuna-huna sa work again.

Sakto. For tonight, okay ra nga dili nimo anay solve-on ang issue sa office. Makapahulay sa imong body ug mind first. Ug pwede pud nimo isulti sa imong ate nga dili ka okay karon para dili nimo kinahanglan magpanggap nga fine.

Sige. I think mas maayo gyud nga isulti nako niya.

Camille, since niabot na sa point nga grabe ang emotional distress ug naapektuhan na imong sleep, appetite, ug adlaw-adlaw nga functioning, maayo pud nga makastorya ka ug mental health professional.

Psychologist?

Yes, pwede ka mangita ug psychologist for a proper consultation. Pwede pud ka mangutana sa inyong local health services kung unsay available nga mental health support ug asa ka mahimong ma-connect.

Okay. I think willing ko ana.

Maayo. Dili nimo kinahanglan hulaton nga mosamot pa before ka mangayo ug support.

Oo. Murag mas okay ko knowing nga naa koy option.

For tonight, stay close sa imong ate or another trusted person. Ug kung mausab ang imong gibati ngadto sa point nga mobati ka nga dili na ka safe, pangayo dayon ug immediate help ug ayaw pag-inusara.

Sige, ma'am.


Before ta mahuman, Camille, kinsa imong unang duolon after ani nga call?

Akong ate. Moingon ko niya nga dili gyud ko okay today and maybe I need someone to stay with me.

Maayo na nga step. Dili kinahanglan nga ma-explain nimo tanan niya dayon. Pwede ra nimo sugdan sa "Dili ko okay karon, pwede ko nimo ubanan?"

Sige. Murag kaya nako na.

Kumusta imong feeling compared sa pagsugod nato?

Medyo lighter. Wala pa nawala akong problema, pero dili na kaayo gubot akong huna-huna.

Maayo. One step at a time lang karon. Ayaw sa pag-demand nga kinahanglan okay na dayon ka.

Thank you kaayo, ma'am. Needed gyud nako nga makastorya ug someone.

Salamat pud nga nitawag ka ug nisulti sa imong gibati. Before ta mo-end, safe ra gihapon ka?

Oo, safe ra ko.

Sige, Camille. Duol sa imong ate karon ug hatagi ug chance imong kaugalingon nga makapahuay. Maayong hapon.

Maayong hapon pud, ma'am. Thank you.
"""

        result = analyze(text, risk_assessment="Low Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]

        self.assertEqual(result["fields"]["callerName"], "Camille")
        self.assertEqual(result["fields"]["callerAge"], 29)
        self.assertEqual(result["fields"]["callerGender"], "Female")
        self.assertEqual(result["fields"]["callerStatus"], "Single")
        self.assertEqual(result["fields"]["callerLocation"], "Lapu-Lapu City")
        self.assertEqual(categories, ["Given Referrals", "Psychoeducation"])
        self.assertEqual(
            lines[0], "Nitawag ang caller tungod sa Work/Employment Problem."
        )
        for phrase in (
            "dili makatulog og tarong",
            "gusto lang nga mawala",
            "nagsige og hilak",
            "empty ang pamati",
        ):
            self.assertIn(phrase, lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertEqual(lines[2], "Sa risk assessment, low risk.")
        self.assertEqual(
            [
                (entity["label"], entity["text"])
                for entity in result["entities"]
                if entity["label"] == "NAME"
            ],
            [("NAME", "Camille")],
        )

    def test_handles_child_development_concern_without_false_guidance_referral(self):
        text = (
            "Hello, Tawag Paglaum ni. Ako si Liza. Unsa may nahitabo?\n\n"
            "Naa koy problema bahin sa akong anak. Lisod siya mosunod og simple "
            "instructions.\n\n"
            "Unsa iyang edad karon?\n\n"
            "Six years old.\n\n"
            "Unsa imong gibati sa dihang gisultihan ka sa teacher?\n\n"
            "Nahadlok ko. Nakaingon iyang teacher nga kinahanglan siya og extra "
            "guidance.\n\n"
            "Unsa diay imong ngalan?\n\n"
            "Maricel.\n\n"
            "Pila na imong edad?\n\n"
            "Thirty-four.\n\n"
            "Asa ka nagpuyo karon?\n\n"
            "Sa Talisay ko nagpuyo.\n\n"
            "Unsa imong gender?\n\n"
            "Female.\n\n"
            "Married ka or single?\n\n"
            "Married ko.\n\n"
            "Kumusta ka mismo ani tanan?\n\n"
            "Oo. Sige kog worry. Usahay gabii na kaayo ko makatulog kay "
            "maghunahuna ko.\n\n"
            "Unsay kasagaran mosulod sa imong hunahuna?\n\n"
            '"Unsa kaha kung dili siya maka-catch up?" "Unsa kaha kung '
            'kinahanglan niya og special nga support?" Daghan kaayo kog '
            "questions pero wala koy klarong tubag.\n\n"
            "Murag ang uncertainty gyud ang pinakabug-at para nimo.\n\n"
            "Oo. Mas okay pa siguro kung kahibalo ko unsa akong buhaton. Karon "
            "kay sige ra kog search online.\n\n"
            "Nakaapekto ba sa imong appetite o energy?\n\n"
            "Usahay dili ko gutom. Pero mostly anxiety ug sige kog hunahuna ang "
            "problema.\n\n"
            "Maricel, mangutana lang ko para makasiguro ko sa imong safety. "
            "Nakaabot ba ka sa punto nga nakahunahuna ka nga pasakitan imong "
            "kaugalingon?\n\n"
            "Wala, ma'am. Wala gyud.\n\n"
            "Okay. Karon, safe ra ka sa inyong balay?\n\n"
            "Oo, safe ra ko.\n\n"
            "Sige. At least klaro nga wala kay immediate danger karon.\n\n"
            "Maricel, murag dili man kinahanglan nga ikaw ra ang mag-figure out "
            "ani tanan. Ang importante karon kay makuha ninyo ang sakto nga "
            "assessment gikan sa qualified professional.\n\n"
            "Mao pud akong gusto. Pero wala gyud ko kabalo asa magsugod.\n\n"
            "Pwede nato hinay-hinayon. Isulat lang ang mga behavior nga imong "
            "nabantayan. Ayaw pud basola imong kaugalingon.\n\n"
            "Okay. Salamat.\n\n"
            "Based sa imong gi-share, mas maayo nga ma-assess siya sa child "
            "development or mental health professional. Pwede tika ma-refer sa "
            "psychologist.\n\n"
            "Yes, gusto ko ana.\n\n"
            "Sige. Dalha ang observations sa teacher para sa assessment.\n\n"
            "Okay. Mangayo ko og copy.\n\n"
            "Before ta mag-end, unsa imong unang buhaton?\n\n"
            "Istoryahan nako akong husband, then mangita mi og psychologist.\n\n"
            "Maayo na nga next steps. One step at a time lang.\n"
        )

        result = analyze(text, risk_assessment="Low Risk")
        lines = result["summary_bisaya"].splitlines()
        categories = result["field_meta"]["intervention"]["categories"]
        caller_text = extract_caller_text(text)

        self.assertEqual(result["fields"]["callerName"], "Maricel")
        self.assertEqual(result["fields"]["callerAge"], 34)
        self.assertEqual(result["fields"]["callerGender"], "Female")
        self.assertEqual(result["fields"]["callerStatus"], "Married")
        self.assertEqual(result["fields"]["callerLocation"], "Talisay City")
        self.assertEqual(categories, ["Given Referrals", "Psychoeducation"])
        self.assertNotIn("Referred to Guidance Counselors", categories)
        self.assertEqual(lines[0], "Nitawag ang caller tungod sa Family Problem.")
        for phrase in (
            "dili makatulog og tarong",
            "gikulbaan",
            "nawad-an og gana mokaon",
            "sige og overthink",
        ):
            self.assertIn(phrase, lines[1])
        self.assertNotIn("adunay mga hunahuna sa pagpakamatay", lines[1])
        self.assertEqual(lines[2], "Sa risk assessment, low risk.")
        self.assertIn("referral", lines[3])
        self.assertIn("psychoeducation", lines[3])
        self.assertIn("Unsa kaha kung dili siya maka-catch up?", caller_text)
        self.assertNotIn("murag dili man kinahanglan nga ikaw ra", caller_text)
        self.assertEqual(
            [
                (entity["label"], entity["text"])
                for entity in result["entities"]
                if entity["label"] == "NAME"
            ],
            [("NAME", "Maricel")],
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
