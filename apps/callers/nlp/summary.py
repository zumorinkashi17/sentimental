"""Build the structured Bisaya summary used by the documentation panel."""

from __future__ import annotations

import re

_NON_WORD = re.compile(r"[^a-z0-9]+")

_PASSIVE_DEATH_WISH = "naglaom nga dili na momata"
_ACTIVE_SI_PHRASE = "adunay mga hunahuna sa pagpakamatay"
_SELF_HARM_PHRASE = "adunay mga hunahuna sa pagpasakit sa kaugalingon"
_SUICIDE_DENIAL = re.compile(
    r"\b(?:"
    r"wala(?: sad)?(?: man)?(?:\s+(?:hinuon|gyud|jud|kaayo|lang))?"
    r"(?: ko| koy| akoy)? nagplano(?: nga)? "
    r"(?:magpakamatay|mamatay|hikog|pasakitan ang akong kaugalingon)"
    r"|wala(?: sad)?(?: man)?(?:\s+(?:hinuon|gyud|jud|kaayo|lang))?"
    r"(?: ko| koy| akoy)? "
    r"(?:plano|intensyon|hunahuna)(?: nga| og| sa)? "
    r"(?:magpakamatay|mamatay|hikog|pasakitan ang akong kaugalingon)"
    r"|di(?:li)?(?: man)?(?: sad)?(?: ko)? gusto(?:ng)? "
    r"(?:mamatay|magpakamatay|hikog)"
    r"|wala(?: sad)?(?: man)?(?:\s+(?:hinuon|gyud|jud|kaayo|lang))?"
    r"(?: ko| koy| akoy)? naghunahuna(?: nga| og| sa)? "
    r"(?:magpakamatay|mamatay|hikog|pasakitan ang akong kaugalingon)"
    r"|(?:nahadlok|hadlok|mahadlok|kahadlok|scared|afraid)"
    r"(?:\s+(?:kaayo|gyud|jud|man|lang))?"
    r"(?:\s+(?:ko|siya|mi|kami))?"
    r"(?:\s+(?:nga|na))?\s+"
    r"(?:mo[\s-]?suicide|magpakamatay|mamatay|hikog|"
    r"pasakitan ang akong kaugalingon)"
    r"|pasakitan(?:\s+ang)?\s+akong kaugalingon,?\s+"
    r"(?:wala|wa)(?:\s+(?:man|jud|gyud|ko|koy|nako))?"
    r")\b",
    re.IGNORECASE,
)

_NEGATION_WORDS = {
    "wala",
    "wa",
    "dili",
    "di",
    "hindi",
    "ayaw",
    "not",
    "never",
    "no",
}
_NEGATION_SENSITIVE_REASONS = {
    "Self-harming and Suicidal Attempt/Crisis",
    "Suicidal Ideation",
    "Inquiry",
}

_BIPOLAR_PATTERN = re.compile(
    r"^(?=.*\b(?:hyper|hyperactive|paspas akong utok|mood swing|mood swings)\b)"
    r"(?=.*\b(?:ma down|kaguol|depress|down kaayo)\b)",
    re.IGNORECASE,
)

_BURNOUT_PATTERN = re.compile(
    r"(?=.*\b(?:work|trabaho|office|shift|duty)\b)"
    r"(?=.*\b(?:breakdown|puno na|asenso)\b)",
    re.IGNORECASE,
)

_PANIC_PATTERN = re.compile(
    r"(?=.*\b(?:panic attack|panic|kulba|gikulbaan|kuyawan|makulbaan|atakihon)\b)"
    r"(?=.*\b(?:dughan|ginhawa|kasingkasing|heart|kurog|nangurog|lipong)\b)",
    re.IGNORECASE,
)

_GRIEF_PATTERN = re.compile(
    r"\b(?:gilubong|lubong|namatyan|namatay|funeral|burial|buried)\b",
    re.IGNORECASE,
)

_DEPRESSION_PATTERN = re.compile(
    r"(?=.*\b(?:numb|empty|wala nay pulos|wala nay kalipay|wala koy kalipay|"
    r"wa na koy ma feel)\b)"
    r"(?=.*\b(?:wala koy gana|wala gyud koy gana|mag higda|magmata|"
    r"dili makatulog|gikapoy|kapoy)\b)",
    re.IGNORECASE,
)

_THIRD_PARTY_CALL = re.compile(
    r"\b(?:dili ako ang naa(?:y)? problema|"
    r"bahin ni sa akong (?:amigo|migo|friend|higala)|"
    r"para sa laing tawo|"
    r"akong (?:amigo|migo|friend|higala))\b",
    re.IGNORECASE,
)

_THIRD_PARTY_REPORT = re.compile(
    r"\b(?:niingon|ingon|nagsulti|nisulti|nag-ingon|ni-post|nag-post)\s+"
    r"(?:siya|niya|si\s+\w+|ni\s+\w+)\b[^.!?\n]*[.!?]?",
    re.IGNORECASE,
)

_FALLBACK_REASON = "wala mailhi nga rason"
_FALLBACK_SYMPTOMS = "wala siya magpaila og partikular nga sintomas"
_FALLBACK_RISK = "wala pa ma-assess"
_FALLBACK_INTERVENTION = "naghatag og emotional support"

_REASON_RULES = (
    (
        "Self-harming and Suicidal Attempt/Crisis",
        (
            "self harm",
            "self-harm",
            "hikog",
            "pasakit sa kaugalingon",
            "suicide attempt",
            "nagpakamatay",
        ),
    ),
    (
        "Suicidal Ideation",
        (
            "suicidal",
            "suicide",
            "gusto mamatay",
            "gusto na mamatay",
            "gusto nako mamatay",
            "magpakamatay",
            "tapuson ang kinabuhi",
            "tapuson na lang",
            "ambak",
            "mawala na lang",
        ),
    ),
    ("Rape", ("rape", "gipugos", "sexual assault")),
    (
        "Sexual Harassment and Sexual Abuse",
        ("sexual harassment", "sexual abuse", "panghilabot", "harass"),
    ),
    (
        "Domestic Abuse",
        (
            "domestic abuse",
            "bunal",
            "sagpa",
            "gisagpa",
            "gisumbag",
            "gitukmod",
            "gibukbok",
            "gikulata",
            "kulatahon",
            "binukbokay",
            "nanapat",
            "abuso sa panimalay",
            "pagpangabuso",
            "pangabuso",
        ),
    ),
    (
        "Physical Abuse",
        (
            "physical abuse",
            "bunal",
            "sagpa",
            "gisagpa",
            "gisumbag",
            "gitukmod",
            "gibukbok",
            "gibunalan",
            "gikulata",
            "kulatahon",
            "binukbokay",
        ),
    ),
    (
        "Alcohol Dependence",
        ("alcohol", "hubog", "bisyo", "drinking"),
    ),
    ("Drug Addiction", ("drug", "droga", "shabu", "marijuana", "adik")),
    ("Gambling Problem", ("gambling", "sugal", "casino")),
    (
        "Academic Problem",
        (
            "scholarship",
            "grades",
            "tuition",
            "school works",
            "schoolwork",
            "subject",
            "subjects",
            "major subject",
            "major subjects",
            "tungod sa skwela",
            "tungod sa eskwela",
            "problema sa skwela",
            "problema sa eskwela",
            "backlog",
            "backlogs",
            "lessons",
            "lesson",
            "blockmates",
            "plates",
            "midterms",
            "graduate",
            "graduation",
            "academic",
        ),
    ),
    (
        "Financial Problem",
        (
            "financial",
            "kwarta",
            "pobre",
            "ikabayad",
            "budget",
            "utang",
            "money",
            "negosyo",
            "business",
            "savings",
            "na-close",
            "nag-close",
            "ni-close",
            "bankrupt",
            "na-bankrupt",
            "zero na",
            "napildi",
            "gibuhos nako tanan",
            "gipusta nako tanan",
        ),
    ),
    ("Work/Employment Problem", ("trabaho", "work", "employment", "boss", "overtime")),
    ("Marital Problem", ("asawa", "bana", "marital", "kaminyoon")),
    (
        "Relationship Problem",
        (
            "relasyon",
            "relationship",
            "uyab",
            "partner",
            "nasakpan nako siya nga naay lain",
            "nag away mi sa akong uyab",
            "nag away mi sa akong partner",
            "away mi sa akong uyab",
        ),
    ),
    (
        "Family Problem",
        (
            "akong pamilya",
            "among pamilya",
            "pamilya nako",
            "pamilya namo",
            "problema sa pamilya",
            "family problem",
            "my family",
            "mama",
            "papa",
            "anak",
        ),
    ),
    (
        "Anxiety",
        (
            "anxiety",
            "kulba",
            "gikulbaan",
            "panic",
            "kakulba",
            "makulbaan",
            "overthink",
            "overthinking",
        ),
    ),
    ("Panic Attack", ("panic attack", "panic")),
    (
        "Depression",
        (
            "depress",
            "depresyon",
            "down",
            "kaguol",
            "nawala na akong gana",
            "nawala akong gana",
            "wala koy gana",
            "wala na koy gana",
            "wala koy excitement",
            "wala koy enjoyment",
            "wala koy energy",
            "wala koy pulos",
            "empty",
            "dili na ko ganahan mobangon",
            "magpundo sa kwarto",
        ),
    ),
    ("Grief", ("grief", "namatay", "patay", "kawala")),
    (
        "Symptoms of Insomnia",
        (
            "insomnia",
            "sleep problem",
            "dili makatulog",
            "dili katulog",
            "di makatulog",
            "di katulog",
            "dili gyud ko katulog",
            "di gyud ko katulog",
            "dili gyud makatulog",
            "di gyud makatulog",
            "dili ko katulog",
            "di ko katulog",
            "dili ko makatulog",
            "di ko makatulog",
            "dili nako katulog",
            "di nako katulog",
            "dili nako makatulog",
            "di nako makatulog",
            "lisod makatulog",
            "lisod katulog",
            "wala katulog",
            "gabii na kaayo ko makatulog",
            "gabii na ko makatulog",
            "kulang sa tulog",
            "mag buntag",
            "tutok sa kisame",
        ),
    ),
    (
        "Burnout",
        (
            "burnout",
            "burn out",
            "stress",
            "stressed",
            "work stress",
            "human sa akong shift",
            "tig atiman",
            "tig comfort",
            "emotional overload",
            "empty na kaayo ko",
            "empty na ko",
            "wala nakoy ihatag",
            "gi absorb nako",
            "caregiver fatigue",
        ),
    ),
    (
        "Bullying",
        (
            "bully",
            "bullying",
            "kanchawan",
            "gikanchawan",
            "gi-kanchawan",
            "nagkanchawan",
            "binuangan",
            "gibinuangan",
            "gi-binuangan",
            "gi-suwat-suwatan",
            "gisuwat-suwatan",
            "gikuha akong bag",
            "ilabay sa basurahan",
        ),
    ),
    (
        "Cyberbullying",
        (
            "cyberbully",
            "cyberbullying",
            "online",
            "dummy account",
            "facebook",
            "hate messages",
            "edited pictures",
            "edited nga pictures",
            "gi-tag",
            "na-share",
            "online harassment",
            "identity theft",
        ),
    ),
    ("PTSD", ("ptsd",)),
    (
        "Trauma",
        ("trauma", "traumatic", "nasunog", "sunog", "sunogon", "kalayo", "fire"),
    ),
    (
        "Medical/Medication Concern",
        ("medication", "tambal", "doctor", "medical", "sakit sa lawas"),
    ),
    ("Legal Advice", ("legal", "abogado", "kaso")),
    ("Abortion", ("abortion", "abort")),
    ("ADHD", ("adhd",)),
    ("Bipolar and OCD", ("bipolar", "ocd")),
    ("Acute Stress Disorder", ("acute stress",)),
    (
        "Anger Management Issue",
        (
            "anger",
            "kasuko",
            "init sa ulo",
            "init kaayo akong ulo",
            "init akong ulo",
            "init ang ulo",
            "kalagot",
            "grabeng kalagot",
            "dali masuko",
            "dali ra ko masuko",
            "nasuko ko",
            "nasuko kaayo ko",
            "nasuko gyud ko",
            "nasuko man ko",
            "manumbag",
            "makapasakit kog tawo",
            "makapatay kog tawo",
        ),
    ),
    ("Career Path Crisis", ("career",)),
    ("Current Social Issue", ("social issue",)),
    ("Emotional Crisis", ("emotional crisis", "crisis")),
    (
        "Feelings of Sadness and Loneliness",
        (
            "kamingaw",
            "mingaw",
            "lonely",
            "alone",
            "sadness",
            "empty nest",
            "wala nay purpose",
            "nawala akong purpose",
            "nawad-an og purpose",
            "blangko ang adlaw",
        ),
    ),
    ("Global Developmental Delay", ("developmental delay",)),
    ("Indentity Confusion", ("identity", "indentity")),
    ("Inquiry", ("inquiry", "pangutana")),
    ("Interpersonal Conflict", ("conflict", "away")),
    ("Intimacy Problems", ("intimacy",)),
    ("Needed Referral", ("referral",)),
    (
        "Postpartum Depression",
        (
            "postpartum",
            "nanganak",
            "bag ong nanganak",
            "wala koy ma feel nga kalipay",
            "wala koy kalipay",
            "dili ko ganahan mogunit",
            "dili ganahan mogunit",
            "bati nga pagka inahan",
            "pagka inahan",
        ),
    ),
    ("Psychiatric Emergency", ("psychiatric emergency",)),
    ("Psychosomatic Pain", ("psychosomatic",)),
    (
        "Quarter Life Crisis",
        (
            "quarter life",
            "quarter-life",
            "mid twenties",
            "mid-twenties",
            "naglibog sa akong kinabuhi",
            "naglibog ko sa akong kinabuhi",
            "koy padulngan",
            "way padulngan",
            "unsa akong purpose",
            "unsay akong purpose",
            "unsa man gyud akong purpose",
            "na-left behind",
            "left behind",
            "na stuck",
            "na-stuck",
            "kumpara nila",
            "compare",
            "itandi",
        ),
    ),
    (
        "Schizophrenia/Psychiatric Symptoms",
        ("schizophrenia", "hallucination"),
    ),
)

_SYMPTOM_RULES = (
    (
        "nagsige og hilak",
        (
            "hilak",
            "makahilak",
            "nakahilak",
            "mihilak",
            "mohilak",
            "mohilak na lang ko",
            "maghilak sad ko",
            "maghilak ko",
            "crying",
            "cry",
        ),
    ),
    (
        "gisagpa ug gitukmod",
        ("gisagpa", "gitukmod", "gibukbok", "gibunalan"),
    ),
    (
        "sakit ang abaga",
        ("sakit akong abaga", "sakit kaayo akong abaga", "sakit ang abaga"),
    ),
    (
        "nagsakit ang tiyan",
        (
            "nagsakit akong tiyan",
            "nagsakit ang tiyan",
            "sakit akong tiyan",
            "sakit ang tiyan",
            "stomach pain",
        ),
    ),
    (
        "naghubag ang aping",
        (
            "naghubag akong aping",
            "naghubag ang aping",
            "nagpasa akong lawas",
            "may pasa akong lawas",
            "may pasa sa akong lawas",
            "nag-violet akong aping",
            "nagbukol akong ulo",
        ),
    ),
    (
        "dili makaginhawa og tarong",
        (
            "dili makaginhawa",
            "di makaginhawa",
            "dili ko makaginhawa",
            "di ko makaginhawa",
            "dili ko kaginhawa",
            "di ko kaginhawa",
            "dili ko kaginhawa og tarong",
            "di ko kaginhawa og tarong",
            "dili nako ka ginhawa",
            "di nako ka ginhawa",
            "naglisod kog ginhawa",
            "naglisod ko og ginhawa",
            "lisod kaayo ko ginhawa",
            "lisod ko ginhawa",
            "lisod kog ginhawa",
            "lisod kaayo akong ginhawa",
            "lisod akong ginhawa",
            "dili ka ginhawa",
            "di ka ginhawa",
            "dili kapugngan akong breathing",
            "dili ko kapugngan akong breathing",
            "kulang sa hangin",
            "kulang ko sa hangin",
            "shortness of breath",
        ),
    ),
    (
        "kalit nga pagka-down ug kadasig",
        (
            "kalit lang ko ma down",
            "kalit lang ko ma-down",
            "kalit nga pagka down",
            "mood swing",
            "mood swings",
            "hyper kaayo ko",
            "hyper kaayo",
            "paspas akong utok",
            "daghan kaayog huna huna",
        ),
    ),
    (
        "gikulbaan",
        (
            "kulba",
            "kakulba",
            "kulbaan",
            "gikulbaan",
            "makulbaan",
            "anxiety",
            "anxious",
            "panic",
        ),
    ),
    (
        "mupaspas ang heartbeat",
        (
            "mupaspas akong heartbeat",
            "mupaspas ang heartbeat",
            "paspas akong heartbeat",
        ),
    ),
    ("nagsuka", ("suka", "vomit", "nagsuka")),
    (
        "nagkurog ang lawas",
        (
            "nagkurog akong tibuok lawas",
            "nagkurog ang lawas",
            "nagkurog akong lawas",
            "nagkurog tibuok lawas",
            "tibuok lawas nagkurog",
            "mokurog akong tibuok lawas",
            "mokurog ang lawas",
            "mokurog akong lawas",
            "mokurog tibuok lawas",
            "nagkurog ko",
            "nagkurog ako",
            "mag-kurog",
            "mag kurog",
        ),
    ),
    (
        "nagkurog ang kamot",
        (
            "nagkurog ang kamot",
            "nagkurog ang mga kamot",
            "nagkurog akong kamot",
            "nagkurog akong mga kamot",
            "kurog akong kamot",
            "kurog akong mga kamot",
            "mokurog ang kamot",
            "mokurog ang mga kamot",
            "mokurog akong kamot",
            "mokurog akong mga kamot",
            "kurog ang kamot",
            "kurog ang mga kamot",
            "kamot nagkurog",
            "mangurog akong kamot",
            "mangurog ang kamot",
            "mangurog akong mga kamot",
            "shaky hands",
            "trembling hands",
        ),
    ),
    (
        "racing thoughts",
        (
            "galumba-lumba akong huna-huna",
            "galumba lumba akong huna huna",
            "galumba-lumba ang akong huna-huna",
            "paspas akong huna-huna",
            "paspas ang akong huna-huna",
            "racing thoughts",
            "saba kaayo akong utok",
            "akong utok saba kaayo",
            "daghan kaayo kog huna-huna",
        ),
    ),
    (
        "compulsive handwashing",
        (
            "panghugas sa akong kamot",
            "panghugas sa kamot",
            "sige kog panghugas",
            "sige ko panghugas",
            "nanghugas sa kamot",
            "compulsion",
            "compulsions",
            "nag-dugo akong kamot",
            "nagdugo akong kamot",
        ),
    ),
    (
        "sakit ang kamot",
        (
            "sakit akong kamot",
            "sakit akong mga kamot",
            "sakit kaayo akong kamot",
            "sakit kaayo akong mga kamot",
            "sakit ang kamot",
            "sakit ang mga kamot",
        ),
    ),
    (
        "nanghagdaw ang kamot",
        (
            "nanghagdaw akong kamot",
            "nanghagdaw akong mga kamot",
            "nanghagdaw ang kamot",
            "nanghagdaw ang mga kamot",
        ),
    ),
    (
        "nagkurog ang tuhod",
        (
            "nagkurog akong tuhod",
            "nagkurog ang tuhod",
            "nagkurog akong mga tuhod",
            "nagkurog ang mga tuhod",
            "nangurog akong tuhod",
            "nangurog ang tuhod",
        ),
    ),
    (
        "paghuot sa totonlan",
        (
            "paghuot sa totonlan",
            "naghuot akong totonlan",
            "naghuot ang totonlan",
            "nagsakit akong totonlan",
            "sakit akong totonlan",
            "sakit ang totonlan",
        ),
    ),
    (
        "nagkurog ang dughan",
        (
            "nagkurog ang dughan",
            "mokurog ang dughan",
            "kurog akong dughan",
            "nagkurog akong dughan",
            "mokurog akong dughan",
            "kurog ang dughan",
        ),
    ),
    (
        "numb ang kamot",
        (
            "numb ang kamot",
            "numb ang mga kamot",
            "numb akong kamot",
            "numb akong mga kamot",
            "numb ug bugnaw akong mga kamot",
            "bugnaw akong kamot",
            "bugnaw ang kamot",
            "bugnaw akong mga kamot",
            "bugnaw ang mga kamot",
        ),
    ),
    ("gipaningot", ("gipaningot", "paningot", "singot", "sweat")),
    (
        "mobuto ang dughan",
        (
            "mobuto",
            "mobuto ang dughan",
            "mubuto",
            "mubuto ang dughan",
            "mubuto akong dughan",
            "maghuot ang dughan",
            "maghuot akong dughan",
            "maghuot kaayo akong dughan",
            "kahuot sa dughan",
            "kahuot",
            "nagtuok sa akong kasing kasing",
            "nagtuok sa akong dughan",
            "murag naay nagtuok",
            "nibuto",
            "nibuto ang dughan",
            "nibuto akong dughan",
            "naghuot akong dughan",
            "naghuot ang dughan",
            "naghuot kaayo akong dughan",
            "chest tight",
        ),
    ),
    (
        "grabeng kasuko",
        (
            "grabeng kasuko",
            "grabeng kalagot",
            "init kaayo akong ulo",
            "init akong ulo",
            "init ang ulo",
            "kalagot",
            "kasuko",
            "maglagot",
        ),
    ),
    (
        "dali masuko",
        (
            "sapoton",
            "dali masuko",
            "dali ra kaayo ko masuko",
            "dali ra ko masuko",
            "iritable",
            "irritable",
        ),
    ),
    (
        "gusto manumbag",
        (
            "lami manumbag",
            "lami kaayo manumbag",
            "gusto manumbag",
            "gusto ko manumbag",
            "manumbag",
        ),
    ),
    (
        "manginit ang lawas",
        (
            "manginit akong tibuok kalawasan",
            "manginit akong lawas",
            "manginit ang lawas",
            "manginit akong kalawasan",
        ),
    ),
    (
        "mamula ang nawong",
        (
            "mamula akong nawong",
            "mamula ang nawong",
            "mamula akong dunggan",
        ),
    ),
    (
        "bug-at ang dughan",
        ("bug-at ang dughan", "bug-at akong dughan", "bug-at kaayo akong dughan"),
    ),
    (
        "sakit ang dughan",
        (
            "sakit ang dughan",
            "sakit akong dughan",
            "sakit kaayo akong dughan",
            "sakit kaayo ang dughan",
            "sakit sa dughan",
            "nagsakit akong dughan",
            "nagsakit kaayo akong dughan",
            "gikumot akong kasingkasing",
            "gikumot ang kasingkasing",
        ),
    ),
    (
        "nawad-an og gana mokaon",
        (
            "nawad-an og gana",
            "nawad-an nakog gana",
            "nawad-an kog gana",
            "wala koy gana",
            "wala gyud koy gana",
            "wala nakoy gana",
            "wala na koy gana",
            "wala sad koy gana",
            "wala koy gana mokaon",
            "wala na koy gana mokaon",
            "wala nakoy gana mokaon",
            "wala sad koy gana mokaon",
            "wala pa ko nikaon",
            "wala pa nikaon",
            "wala ko nikaon",
            "wala ko nakaon",
            "wala pa ko nakaon",
            "wala pa ko kaon",
            "wala ko kaon",
            "dili ko gutom",
            "wala ko gutoma",
            "wa ko gutoma",
            "usa ra ko ka meal",
            "usa ra ka meal sa tibuok adlaw",
            "usa ka meal sa tibuok adlaw",
            "loss of appetite",
        ),
    ),
    (
        "wala nay kalipay",
        (
            "wala koy ma feel nga kalipay",
            "wa na koy ma feel nga kalipay",
            "wala na koy ma feel nga kalipay",
            "wa na koy ma feel",
            "wala na koy ma feel",
            "wala koy kalipay",
            "wala na koy kalipay",
            "wala nay kalipay",
            "nawala na akong gana sa tanan",
            "nawala akong gana sa tanan",
            "wala koy enjoyment",
            "wala koy excitement",
            "dili ko ganahan mogunit",
            "dili ganahan mogunit",
        ),
    ),
    (
        "grabeng kakapoy",
        (
            "kapoy na kaayo akong lawas",
            "kapoy na akong lawas",
            "kapoy na akong utok",
            "grabeng kakapoy",
            "wala nakoy kusog",
            "wala koy kusog",
            "wala koy gana mulihok",
            "wala koy gana molihok",
        ),
    ),
    (
        "dili ganahan mogawas",
        (
            "dili ganahan mogawas",
            "di ganahan mogawas",
            "di ko ganahan mogawas",
            "dili gusto mogawas",
            "di gusto mogawas",
            "dili makig-storya",
            "di makig-storya",
        ),
    ),
    (
        "wala nay gamit ang kinabuhi",
        (
            "wala nay gamit akong kinabuhi",
            "wala nay gamit ang kinabuhi",
        ),
    ),
    (
        "nawala ang purpose",
        (
            "wala nay purpose",
            "nawala akong purpose",
            "nawad-an og purpose",
            "wala nako makita ang purpose",
            "wala nakita ang purpose",
        ),
    ),
    (
        "gikapoy mabuhi",
        ("kapoy na kaayo mabuhi", "kapoy mabuhi", "kapoy na ko mabuhi"),
    ),
    (
        "gusto lang nga mawala",
        (
            "mawala lang ko",
            "mawala lang ko kadali",
            "mawala lang unta ko",
            "mawala lang unta ko kadali",
            "mawala ko kadali",
            "gusto lang ko mawala",
            "gusto lang nako mawala",
            "gusto ko mawala",
        ),
    ),
    (
        "naglaom nga dili na momata",
        (
            "di na momata",
            "dili na momata",
            "di na ko momata",
            "dili na ko momata",
            "di na nako ma-feel",
            "dili na nako ma-feel",
            "dili na lang unta ko makamata",
            "di na lang unta ko makamata",
            "dili na lang ko makamata",
            "di na lang ko makamata",
            "dili na unta ko makamata",
            "di na unta ko makamata",
            "mopahuway na forever",
            "pahuway na forever",
            "mopahuway na lang",
            "mawala na lang ko",
            "mawala na lang ko kalit",
            "mawala ko kalit",
        ),
    ),
    (
        "nakasinati og kamingaw",
        ("kamingaw", "gikamingaw", "mingaw", "lonely", "alone"),
    ),
    ("nag-inusara", ("inusara", "ako ra usa", "ako na lang usa", "ako ray usa")),
    (
        "gilabad ang ulo",
        (
            "labad",
            "maglabad",
            "headache",
            "nagsakit akong ulo",
            "sakit akong ulo",
            "sakit kaayo akong ulo",
            "sakit na akong ulo",
            "sakit ang ulo",
            "manakit akong ulo",
            "manakit ang ulo",
        ),
    ),
    (
        "nag-blangko ang utok",
        (
            "blangko",
            "blank",
            "dili na ko kasabot sa akong utok",
            "dili ko kasabot sa akong utok",
            "nagsagol na tanan",
            "gubot akong utok",
            "gubot ang utok",
            "gubot kaayo akong utok",
            "naglibog akong utok",
            "libog akong utok",
            "naglibog ko",
        ),
    ),
    ("nahadlok", ("hadlok", "kahadlok", "mahadlok", "scared", "fear")),
    (
        "dili makatulog og tarong",
        (
            "insomnia",
            "dili makatulog",
            "dili katulog",
            "di makatulog",
            "di katulog",
            "dili gyud ko katulog",
            "di gyud ko katulog",
            "dili gyud makatulog",
            "di gyud makatulog",
            "dili ko katulog",
            "di ko katulog",
            "dili ko makatulog",
            "di ko makatulog",
            "dili nako katulog",
            "di nako katulog",
            "dili nako makatulog",
            "di nako makatulog",
            "magmata ko inig kadlawon",
            "magmata inig kadlawon",
            "magmata hantod kadlawon",
            "magmata hangtod kadlawon",
            "mata ko mga alas tres",
            "mata ko alas tres",
            "mata ko sa kadlawon",
            "maghunahuna hangtod buntag",
            "tulog kay gubot",
            "gubot ang tulog",
            "gubot akong tulog",
            "sayo ko matulog pero mata",
            "magmata akong diwa hantod kadlawon",
            "magmata ra sad akong diwa hantod kadlawon",
            "oras ra akong tulog",
            "around five hours lang",
            "five hours lang",
            "lima ka oras lang",
            "magmata ko usahay in the middle of the night",
            "magmata in the middle of the night",
            "lisod makatulog",
            "lisod katulog",
            "lisod kaayo ko makatulog",
            "lisod kaayo ko katulog",
            "lisod ko makatulog",
            "lisod ko katulog",
            "lisod kaayo makatulog",
            "lisod kaayo katulog",
            "makatulog man ko, makamata",
            "makamata ra kog kalit",
            "makamata kog kalit",
            "makamata tunga sa gabii",
            "wala katulog",
            "wala ko katulog",
            "wala ko makatulog",
            "wala ko tulog",
            "wala koy tulog",
            "wala na koy tulog",
            "wala nakoy tulog",
            "wala na koy tulog tarong",
            "wala nakoy tulog tarong",
            "gabii na kaayo ko makatulog",
            "gabii na ko makatulog",
            "kulang sa tulog",
            "sige kog puyat",
            "sigeg puyat",
            "sige og puyat",
            "alas dos o alas tres na ko makatulog",
            "alas tres na ko makatulog",
            "dugay ko makatulog",
            "mag buntag",
            "tutok sa kisame",
        ),
    ),
    (
        "dili maka-focus",
        (
            "dili maka focus",
            "di maka focus",
            "dili nako maka focus",
            "di nako maka focus",
            "dili maka-focus",
            "di maka-focus",
            "dili makafocus",
            "di makafocus",
            "maglisod kog focus",
            "lisod kog focus",
            "wala ko kasabot sa akong gibasa",
            "dili ko kasabot sa akong gibasa",
            "ginapalangan",
            "gipalangan",
            "naglutaw akong paminaw",
        ),
    ),
    (
        "sige og overthink",
        (
            "overthink",
            "over thinking",
            "sige kog overthink",
            "sige ra kog overthink",
            "sige kog huna huna",
            "sige kog hunahuna",
            "sige huna huna",
            "sige og huna huna",
            "replay sa akong utok",
        ),
    ),
    (
        "gikapoy",
        (
            "kapoy",
            "gikapoy",
            "fatigue",
            "tired",
            "wala koy energy",
            "walay energy",
        ),
    ),
    ("nakauwaw", ("ulaw", "shame")),
    ("nagul-an", ("guol", "sadness", "sad kaayo", "sad akong", "sad gyud")),
    (
        "makonsensya",
        (
            "makonsensya",
            "konsensya",
            "guilty",
            "guilt",
            "ma guilty",
            "nakonsensya",
        ),
    ),
    (
        "empty ang pamati",
        (
            "empty ang pamati",
            "empty kaayo akong pamati",
            "empty na kaayo ko",
            "empty na ko",
            "empty kaayo ko",
            "murag empty",
            "walay lami ang pamati",
            "numb kaayo akong feeling",
            "numb akong feeling",
            "numb ang feeling",
            "numb na akong feeling",
        ),
    ),
    (
        "nag-ingon nga wala nay pulos mabuhi",
        (
            "unsa may pulos mabuhi",
            "wala nay pulos mabuhi",
            "walay pulos mabuhi",
            "unsa may kapuslanan",
        ),
    ),
    (
        "wala na siyay paglaom",
        (
            "hopeless",
            "wala nay paglaom",
            "wala na koy paglaom",
            "wala nakoy paglaom",
            "give up",
        ),
    ),
    (
        _SELF_HARM_PHRASE,
        (
            "self harm",
            "self-harm",
            "pasakit sa kaugalingon",
            "pasakitan akong kaugalingon",
            "pasakitan nako akong kaugalingon",
            "ihapak akong ulo",
            "ihapak nako akong ulo",
            "ihapak ang akong ulo",
            "garasan akong kaugalingon",
            "garasan nako akong kaugalingon",
            "garas akong kaugalingon",
            "garasan akong bukton",
            "garasan nako akong bukton",
            "garasan ang bukton",
            "garas akong bukton",
            "nagkuha kog blade",
            "nakakuha kog blade",
            "nagkuha ko og blade",
            "nagkuha kog kutsilyo",
            "nakakuha kog kutsilyo",
            "blade",
            "kutsilyo",
        ),
    ),
    (
        "adunay mga hunahuna sa pagpakamatay",
        (
            "suicide",
            "suicidal",
            "tapuson ang kinabuhi",
            "tapuson na lang",
            "ambak",
            "hikog",
            "magpakamatay",
            "gusto ko mamatay",
            "gusto nako mamatay",
            "gusto na ko mamatay",
            "lami mamatay",
            "lami na kaayo mamatay",
            "muinom og daghang tambal",
            "muinom og tambal",
            "daghang tambal",
            "overdose",
            "i-bangga",
            "ibangga",
            "banggaon",
            "magpabangga",
            "mag-bangga",
            "magbangga",
            "bangga sa truck",
            "i-bangga sa truck",
            "magpaligis",
            "magpa-ligis",
            "magpa ligis",
            "ipaligis",
            "i-paligis",
            "maligsan",
            "paligsan",
            "mahuman na lang tanan",
        ),
    ),
)

_SYMPTOM_PRIORITY = {
    "adunay mga hunahuna sa pagpakamatay": 0,
    "adunay mga hunahuna sa pagpasakit sa kaugalingon": 0,
    "wala na siyay paglaom": 0,
    "naglaom nga dili na momata": 0,
    "gusto lang nga mawala": 1,
    "mobuto ang dughan": 1,
    "grabeng kasuko": 1,
    "gusto manumbag": 1,
    "bug-at ang dughan": 1,
    "sakit ang dughan": 1,
    "gikulbaan": 1,
    "kalit nga pagka-down ug kadasig": 1,
    "dali masuko": 3,
    "wala nay kalipay": 1,
    "grabeng kakapoy": 1,
    "gikapoy mabuhi": 1,
    "dili makatulog og tarong": 1,
    "nag-ingon nga wala nay pulos mabuhi": 1,
    "gisagpa ug gitukmod": 1,
    "sakit ang abaga": 1,
    "nagsakit ang tiyan": 2,
    "naghubag ang aping": 1,
    "dili makaginhawa og tarong": 1,
    "mupaspas ang heartbeat": 2,
    "nagsuka": 2,
    "empty ang pamati": 2,
    "nagkurog ang lawas": 2,
    "nagkurog ang kamot": 2,
    "racing thoughts": 1,
    "compulsive handwashing": 1,
    "sakit ang kamot": 3,
    "nanghagdaw ang kamot": 3,
    "nagkurog ang tuhod": 3,
    "paghuot sa totonlan": 3,
    "nagkurog ang dughan": 2,
    "numb ang kamot": 3,
    "gipaningot": 2,
    "nagsige og hilak": 2,
    "nawad-an og gana mokaon": 2,
    "wala nay gamit ang kinabuhi": 2,
    "nawala ang purpose": 2,
    "dili ganahan mogawas": 3,
    "nakasinati og kamingaw": 3,
    "nag-inusara": 3,
    "dili maka-focus": 3,
    "mamula ang nawong": 3,
    "manginit ang lawas": 3,
    "sige og overthink": 3,
    "gilabad ang ulo": 4,
    "nag-blangko ang utok": 4,
    "nahadlok": 4,
    "makonsensya": 4,
    "gikapoy": 5,
    "nagul-an": 5,
    "nakauwaw": 6,
}

_INTERVENTION_PHRASES = {
    "Referred to Emergency Room": "nag-refer sa emergency room",
    "Referred to Guidance Counselors": "nag-refer sa guidance counselor",
    "Refused Referrals": (
        "nagtanyag og referral apan wala pa kini dawata sa caller"
    ),
    "Others": "naghatag og laing tabang",
    "Responder provided empathetic listening and support": (
        "naminaw ug naghatag og suporta"
    ),
}


def _normalize(text: str) -> str:
    normalized = _NON_WORD.sub(" ", str(text or "").lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _position(text: str, cue: str) -> int:
    normalized_cue = _normalize(cue)
    if not normalized_cue:
        return -1
    if " " in normalized_cue:
        return f" {text} ".find(f" {normalized_cue} ")
    match = re.search(rf"\b{re.escape(normalized_cue)}\b", text)
    return match.start() if match else -1


def _is_negated(text: str, position: int) -> bool:
    before = text[:position].split()[-5:]
    return any(word in _NEGATION_WORDS for word in before)


def _first_match(text: str, rules: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    normalized = _normalize(text)
    if not normalized:
        return ""
    best: tuple[int, int, str] | None = None
    for order, (label, cues) in enumerate(rules):
        positions = []
        for cue in cues:
            position = _position(normalized, cue)
            if position < 0:
                continue
            if label in _NEGATION_SENSITIVE_REASONS and _is_negated(
                normalized, position
            ):
                continue
            positions.append(position)
        if not positions:
            continue
        item = (min(positions), order, label)
        if best is None or item < best:
            best = item
    return best[2] if best else ""


def _caller_symptom_text(caller_text: str) -> str:
    if not _THIRD_PARTY_CALL.search(caller_text):
        return caller_text
    return _THIRD_PARTY_REPORT.sub(" ", caller_text)


def _symptom_phrases(
    text: str, limit: int, preferred_text: str | None = None
) -> list[str]:
    normalized = _normalize(text)
    if not normalized:
        return []
    preferred = _normalize(preferred_text or "")
    matches: list[tuple[int, int, int, int, str]] = []
    denial_spans = [
        match.span() for match in _SUICIDE_DENIAL.finditer(normalized)
    ]
    def denied(position: int) -> bool:
        return any(start <= position < end for start, end in denial_spans)

    active_si_cues = next(
        cues for phrase, cues in _SYMPTOM_RULES if phrase == _ACTIVE_SI_PHRASE
    )
    has_active_si = any(
        (position := _position(normalized, cue)) >= 0
        and not _is_negated(normalized, position)
        and not denied(position)
        for cue in active_si_cues
    )
    for order, (phrase, cues) in enumerate(_SYMPTOM_RULES):
        if phrase == _PASSIVE_DEATH_WISH and has_active_si:
            continue
        positions = []
        for cue in cues:
            position = _position(normalized, cue)
            if position < 0:
                continue
            if phrase in {_ACTIVE_SI_PHRASE, _SELF_HARM_PHRASE} and (
                _is_negated(normalized, position) or denied(position)
            ):
                continue
            if phrase == _PASSIVE_DEATH_WISH and denied(position):
                continue
            if phrase == "nag-inusara" and _is_negated(normalized, position):
                continue
            if phrase == "makonsensya" and re.search(
                r"\b(?:sila|siya)\b", normalized[position : position + 40]
            ):
                continue
            positions.append(position)
        if not positions:
            continue
        in_preferred = bool(
            preferred
            and any(_position(preferred, cue) >= 0 for cue in cues)
        )
        priority = _SYMPTOM_PRIORITY.get(phrase, 99)
        matches.append(
            (priority, 0 if in_preferred else 1, min(positions), order, phrase)
        )
    matches.sort()
    return [phrase for _, _, _, _, phrase in matches[: max(1, limit)]]


def _join_phrases(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} ug {items[1]}"
    return f"{', '.join(items[:-1])}, ug {items[-1]}"


def _clean_label(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"", "select", "select reason", "n/a", "na", "none", "-"}:
        return ""
    return text.rstrip(" .")


def _reason_phrase(
    value: object, caller_text: str, summary_text: str | None = None
) -> str:
    manual = _clean_label(value)
    if manual:
        return manual
    inferred = _first_match(caller_text, _REASON_RULES)
    if not inferred and summary_text:
        inferred = _first_match(summary_text, _REASON_RULES)
    normalized = _normalize(caller_text)
    if _BIPOLAR_PATTERN.search(normalized) or re.search(
        r"\b(?:bipolar|ocd)\b", normalized
    ):
        inferred = "Bipolar and OCD"
    if inferred in {
        "Work/Employment Problem",
        "Burnout",
        "Marital Problem",
        "Family Problem",
    } and _BURNOUT_PATTERN.search(normalized):
        inferred = "Burnout"
    if (
        inferred in {"Anxiety", "Burnout", "Acute Stress Disorder"}
        and _PANIC_PATTERN.search(normalized)
    ):
        inferred = "Panic Attack"
    if (
        inferred in {"Family Problem", "Relationship Problem", "Depression"}
        and _GRIEF_PATTERN.search(normalized)
    ):
        inferred = "Grief"
    if inferred in {"Relationship Problem", "Family Problem", "Marital Problem"}:
        abuse_rules = tuple(
            rule
            for rule in _REASON_RULES
            if rule[0] in {"Domestic Abuse", "Physical Abuse"}
        )
        abuse = _first_match(caller_text, abuse_rules)
        if not abuse and summary_text:
            abuse = _first_match(summary_text, abuse_rules)
        if abuse:
            inferred = abuse
    if (
        inferred in {"Family Problem", "Marital Problem"}
        and _DEPRESSION_PATTERN.search(normalized)
    ):
        inferred = "Depression"
    return inferred or _FALLBACK_REASON


def _symptom_phrase(
    caller_text: str, limit: int, summary_text: str | None = None
) -> str:
    phrases = _symptom_phrases(caller_text, limit, preferred_text=summary_text)
    return _join_phrases(phrases) if phrases else _FALLBACK_SYMPTOMS


def _risk_phrase(value: object) -> str:
    cleaned = _clean_label(value)
    if not cleaned:
        return _FALLBACK_RISK
    lowered = cleaned.lower()
    if lowered in {"low", "medium", "high"}:
        lowered = f"{lowered} risk"
    return lowered


def _intervention_phrase(categories: list[str] | tuple[str, ...] | str | None) -> str:
    if isinstance(categories, str):
        labels = [categories] if categories else []
    else:
        labels = [label for label in (categories or []) if label]
    if not labels:
        return _FALLBACK_INTERVENTION

    parts: list[str] = []
    for label in labels:
        if label in {"Given Referrals", "Psychoeducation", "Others"}:
            continue
        phrase = _INTERVENTION_PHRASES.get(label)
        if phrase:
            parts.append(phrase)

    referral_objects: list[str] = []
    if (
        "Given Referrals" in labels
        and "Referred to Guidance Counselors" not in labels
        and "Refused Referrals" not in labels
    ):
        referral_objects.append("referral")
    if "Psychoeducation" in labels:
        referral_objects.append("psychoeducation")
    if "Others" in labels:
        referral_objects.append("laing tabang")
    if referral_objects:
        parts.append(f"naghatag og {_join_phrases(referral_objects)}")

    return ", ".join(parts) if parts else _FALLBACK_INTERVENTION


def build_summary(
    caller_text: str,
    *,
    summary_text: str | None = None,
    reason_for_calling: object = "",
    risk_assessment: object = "",
    intervention_categories: list[str] | tuple[str, ...] | str | None = None,
    max_symptoms: int = 4,
) -> str:
    """Return the four-line Bisaya summary required by the call form.

    ``summary_text`` is the TextRank-selected caller extract. It is used as a
    tie-breaker for symptom selection; reason inference uses the full caller
    text first so short extracts cannot introduce false positives.
    """
    reason = _reason_phrase(reason_for_calling, caller_text, summary_text)
    symptoms = _symptom_phrase(
        _caller_symptom_text(caller_text), max_symptoms, summary_text
    )
    risk = _risk_phrase(risk_assessment)
    intervention = _intervention_phrase(intervention_categories)
    return "\n".join(
        (
            f"Nitawag ang caller tungod sa {reason}.",
            f"Gipadayag niya nga {symptoms}.",
            f"Sa risk assessment, {risk}.",
            f"Ang responder {intervention}.",
        )
    )


_EN_REASON_TRANSLATIONS = {
    _FALLBACK_REASON: "an unidentified reason",
}

_EN_SYMPTOM_TRANSLATIONS = {
    "nagsige og hilak": "frequent crying",
    "gisagpa ug gitukmod": "being slapped and pushed",
    "sakit ang abaga": "shoulder pain",
    "nagsakit ang tiyan": "stomach pain",
    "naghubag ang aping": "swollen cheek",
    "dili makaginhawa og tarong": "difficulty breathing",
    "kalit nga pagka-down ug kadasig": (
        "sudden mood drops and energy shifts"
    ),
    "gikulbaan": "feeling nervous",
    "mupaspas ang heartbeat": "heart racing",
    "nagsuka": "vomiting",
    "nagkurog ang lawas": "body trembling",
    "nagkurog ang kamot": "hand trembling",
    "racing thoughts": "racing thoughts",
    "compulsive handwashing": "compulsive handwashing",
    "sakit ang kamot": "hand pain",
    "nanghagdaw ang kamot": "hand tremor",
    "nagkurog ang tuhod": "knee trembling",
    "paghuot sa totonlan": "throat tightness",
    "nagkurog ang dughan": "chest trembling",
    "numb ang kamot": "hand numbness",
    "gipaningot": "sweating",
    "mobuto ang dughan": "chest tightness",
    "grabeng kasuko": "intense anger",
    "dali masuko": "irritability",
    "gusto manumbag": "urge to punch",
    "manginit ang lawas": "feeling hot",
    "mamula ang nawong": "face flushing",
    "bug-at ang dughan": "chest heaviness",
    "sakit ang dughan": "chest pain",
    "nawad-an og gana mokaon": "loss of appetite",
    "wala nay kalipay": "loss of pleasure",
    "grabeng kakapoy": "severe fatigue",
    "dili ganahan mogawas": "avoiding going out",
    "wala nay gamit ang kinabuhi": "feeling life is meaningless",
    "nawala ang purpose": "loss of purpose",
    "gikapoy mabuhi": "tired of living",
    "naglaom nga dili na momata": "hoping not to wake up",
    "gusto lang nga mawala": "wishing to disappear",
    "nakasinati og kamingaw": "loneliness",
    "nag-inusara": "feeling alone",
    "gilabad ang ulo": "headache",
    "nag-blangko ang utok": "mind going blank",
    "nahadlok": "fear",
    "dili makatulog og tarong": "difficulty sleeping",
    "dili maka-focus": "difficulty focusing",
    "sige og overthink": "overthinking",
    "gikapoy": "fatigue",
    "nakauwaw": "shame",
    "nagul-an": "worry",
    "makonsensya": "guilt",
    "empty ang pamati": "emotional emptiness",
    "nag-ingon nga wala nay pulos mabuhi": "saying life is worthless",
    "wala na siyay paglaom": "hopelessness",
    "adunay mga hunahuna sa pagpasakit sa kaugalingon": (
        "self-harm ideation"
    ),
    "adunay mga hunahuna sa pagpakamatay": "suicidal ideation",
    _FALLBACK_SYMPTOMS: "no specific symptoms were reported",
}

_EN_RISK_TRANSLATIONS = {
    _FALLBACK_RISK: "not yet assessed",
    "low risk": "low risk",
    "medium risk": "medium risk",
    "high risk": "high risk",
}

_EN_INTERVENTION_TRANSLATIONS = {
    "nag-refer sa emergency room": "referred the caller to the emergency room",
    "nag-refer sa guidance counselor": (
        "referred the caller to a guidance counselor"
    ),
    "nagtanyag og referral apan wala pa kini dawata sa caller": (
        "offered a referral that the caller has not accepted yet"
    ),
    "naminaw ug naghatag og suporta": "listened and provided support",
    _FALLBACK_INTERVENTION: "provided emotional support",
}


def _protect_translation_phrases(
    text: str, translations: dict[str, str]
) -> tuple[str, dict[str, str]]:
    placeholders: dict[str, str] = {}
    for index, phrase in enumerate(
        sorted(translations, key=len, reverse=True)
    ):
        if not phrase:
            continue
        token = f"\x00{index}\x00"
        pattern = re.compile(
            rf"(?<!\w){re.escape(phrase)}(?!\w)", re.IGNORECASE
        )
        if pattern.search(text):
            text = pattern.sub(token, text)
            placeholders[token] = translations[phrase]
    return text, placeholders


def _restore_translation_phrases(
    text: str, placeholders: dict[str, str]
) -> str:
    for token, translation in placeholders.items():
        text = text.replace(token, translation)
    return text


def _translate_symptoms(value: str) -> str:
    text, placeholders = _protect_translation_phrases(
        value, _EN_SYMPTOM_TRANSLATIONS
    )
    text = text.replace(" ug ", " and ")
    return _restore_translation_phrases(text, placeholders)


def _translate_intervention(value: str) -> str:
    text, placeholders = _protect_translation_phrases(
        value, _EN_INTERVENTION_TRANSLATIONS
    )
    text = text.replace("naghatag og ", "provided ")
    text = re.sub(r"(?<!\w)referral(?!\w)", "a referral", text)
    text = re.sub(r"(?<!\w)laing tabang(?!\w)", "other assistance", text)
    text = text.replace(" ug ", " and ")
    text = _restore_translation_phrases(text, placeholders)
    parts = text.split(", ")
    if len(parts) > 1:
        return f"{', '.join(parts[:-1])}, and {parts[-1]}"
    return text


def translate_summary(summary: str) -> str:
    """Translate the generated four-line Bisaya summary into English."""
    translated: list[str] = []
    for line in str(summary or "").splitlines():
        if line.startswith("Nitawag ang caller tungod sa ") and line.endswith("."):
            reason = line[len("Nitawag ang caller tungod sa ") : -1].strip()
            reason = _EN_REASON_TRANSLATIONS.get(reason, reason)
            translated.append(f"The caller reached out due to {reason}.")
            continue
        if line.startswith("Gipadayag niya nga ") and line.endswith("."):
            symptoms = line[len("Gipadayag niya nga ") : -1].strip()
            translated.append(
                f"They expressed {_translate_symptoms(symptoms)}."
            )
            continue
        if line.startswith("Sa risk assessment, ") and line.endswith("."):
            risk = line[len("Sa risk assessment, ") : -1].strip()
            risk = _EN_RISK_TRANSLATIONS.get(risk, risk)
            translated.append(f"In the risk assessment, {risk}.")
            continue
        if line.startswith("Ang responder ") and line.endswith("."):
            intervention = line[len("Ang responder ") : -1].strip()
            translated.append(
                f"The responder {_translate_intervention(intervention)}."
            )
            continue
        translated.append(line)
    return "\n".join(translated)
