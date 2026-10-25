"""Build the structured Bisaya summary used by the documentation panel."""

from __future__ import annotations

import re

_NON_WORD = re.compile(r"[^a-z0-9]+")

_PASSIVE_DEATH_WISH = "naglaom nga dili na momata"
_SUICIDE_DENIAL = re.compile(
    r"\b(?:"
    r"wala(?: man)?(?: ko| koy| akoy)? nagplano(?: nga)? "
    r"(?:magpakamatay|mamatay|pasakitan ang akong kaugalingon)"
    r"|wala(?: man)?(?: ko| koy| akoy)? "
    r"(?:plano|intensyon|hunahuna)(?: nga)? "
    r"(?:magpakamatay|mamatay|pasakitan ang akong kaugalingon)"
    r"|di(?:li)?(?: man)?(?: ko)? gusto(?:ng)? mamatay"
    r"|wala(?: ko)? naghunahuna(?: nga)? (?:magpakamatay|mamatay)"
    r")\b",
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
            "mamatay",
            "tapuson ang kinabuhi",
            "tapuson na lang",
            "give up",
            "ambak",
            "mawala na lang",
        ),
    ),
    ("Rape", ("rape", "gipugos", "sexual assault")),
    (
        "Sexual Harassment and Sexual Abuse",
        ("sexual harassment", "sexual abuse", "panghilabot", "harass"),
    ),
    ("Domestic Abuse", ("domestic abuse", "bunal", "sagpa", "abuso sa panimalay")),
    ("Physical Abuse", ("physical abuse", "bunal", "sagpa", "gibunalan")),
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
            "school",
            "subject",
            "academic",
        ),
    ),
    (
        "Financial Problem",
        ("financial", "kwarta", "pobre", "ikabayad", "budget", "utang", "money"),
    ),
    ("Work/Employment Problem", ("trabaho", "work", "employment", "boss", "overtime")),
    ("Marital Problem", ("asawa", "bana", "marital", "kaminyoon")),
    ("Relationship Problem", ("relasyon", "relationship", "uyab", "partner")),
    ("Family Problem", ("pamilya", "parents", "mama", "papa", "anak", "family")),
    ("Anxiety", ("anxiety", "kulba", "gikulbaan", "panic")),
    ("Panic Attack", ("panic attack", "panic")),
    ("Depression", ("depress", "depresyon", "down", "kaguol", "sad")),
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
            "kulang sa tulog",
            "mag buntag",
            "tutok sa kisame",
        ),
    ),
    ("Burnout", ("burnout", "burn out", "stress", "stressed", "work stress")),
    ("Bullying", ("bully", "bullying")),
    ("Cyberbullying", ("cyberbully", "online")),
    ("PTSD", ("ptsd",)),
    ("Trauma", ("trauma", "traumatic")),
    (
        "Medical/Medication Concern",
        ("medication", "tambal", "doctor", "medical", "sakit sa lawas"),
    ),
    ("Legal Advice", ("legal", "abogado", "kaso")),
    ("Abortion", ("abortion", "abort")),
    ("ADHD", ("adhd",)),
    ("Bipolar and OCD", ("bipolar", "ocd")),
    ("Acute Stress Disorder", ("acute stress",)),
    ("Anger Management Issue", ("anger", "kasuko", "init sa ulo")),
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
            "nag-inusara",
            "mag-inusara",
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
    ("Postpartum Depression", ("postpartum",)),
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
    ("nagsige og hilak", ("hilak", "crying", "cry")),
    ("gikulbaan", ("kulba", "gikulbaan", "anxiety", "anxious", "panic")),
    ("nagsuka", ("suka", "vomit", "nagsuka")),
    ("nagkurog ang kamot", ("kurog", "nikig", "shaky", "trembling")),
    ("gipaningot", ("paningot", "singot", "sweat")),
    ("mobuto ang dughan", ("mobuto", "mobuto ang dughan", "chest tight")),
    (
        "bug-at ang dughan",
        ("bug-at ang dughan", "bug-at akong dughan", "bug-at kaayo akong dughan"),
    ),
    (
        "nawad-an og gana mokaon",
        (
            "nawad-an og gana",
            "nawad-an nakog gana",
            "nawad-an kog gana",
            "wala koy gana",
            "wala nakoy gana",
            "loss of appetite",
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
            "wala nay purpose",
            "nawala akong purpose",
            "nawad-an og purpose",
        ),
    ),
    (
        "gikapoy mabuhi",
        ("kapoy na kaayo mabuhi", "kapoy mabuhi", "kapoy na ko mabuhi"),
    ),
    (
        "naglaom nga dili na momata",
        ("di na momata", "dili na momata", "di na nako ma-feel", "dili na nako ma-feel"),
    ),
    (
        "nakasinati og kamingaw",
        ("kamingaw", "mingaw", "lonely", "alone"),
    ),
    ("nag-inusara", ("inusara", "ako ra usa", "ako na lang usa", "ako ray usa")),
    ("gilabad ang ulo", ("labad", "headache")),
    ("nag-blangko ang utok", ("blangko", "blank")),
    ("nahadlok", ("hadlok", "scared", "fear")),
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
            "lisod makatulog",
            "lisod katulog",
            "wala katulog",
            "kulang sa tulog",
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
            "naglutaw akong paminaw",
        ),
    ),
    (
        "dali masuko",
        (
            "dali masuko",
            "dali ra kaayo ko masuko",
            "dali ra ko masuko",
            "maglagot",
            "kalagot",
            "irritable",
        ),
    ),
    (
        "sige og overthink",
        (
            "overthink",
            "over thinking",
            "sige kog overthink",
            "sige ra kog overthink",
            "replay sa akong utok",
        ),
    ),
    ("gikapoy", ("kapoy", "fatigue", "tired")),
    ("nakauwaw", ("ulaw", "shame")),
    ("nagul-an", ("guol", "sad", "sadness")),
    (
        "empty ang pamati",
        ("empty ang pamati", "empty kaayo akong pamati", "murag empty", "walay lami ang pamati"),
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
        "adunay mga hunahuna sa pagpakamatay",
        (
            "suicide",
            "suicidal",
            "tapuson ang kinabuhi",
            "tapuson na lang",
            "ambak",
            "hikog",
            "gusto ko mamatay",
            "gusto nako mamatay",
            "gusto na ko mamatay",
        ),
    ),
)

_SYMPTOM_PRIORITY = {
    "adunay mga hunahuna sa pagpakamatay": 0,
    "wala na siyay paglaom": 0,
    "naglaom nga dili na momata": 0,
    "mobuto ang dughan": 1,
    "bug-at ang dughan": 1,
    "gikulbaan": 1,
    "gikapoy mabuhi": 1,
    "dili makatulog og tarong": 1,
    "nag-ingon nga wala nay pulos mabuhi": 1,
    "nagsuka": 2,
    "empty ang pamati": 2,
    "nagkurog ang kamot": 2,
    "gipaningot": 2,
    "nagsige og hilak": 2,
    "nawad-an og gana mokaon": 2,
    "wala nay gamit ang kinabuhi": 2,
    "dili ganahan mogawas": 3,
    "nakasinati og kamingaw": 3,
    "nag-inusara": 3,
    "dili maka-focus": 3,
    "dali masuko": 3,
    "sige og overthink": 3,
    "gilabad ang ulo": 4,
    "nag-blangko ang utok": 4,
    "nahadlok": 4,
    "gikapoy": 5,
    "nagul-an": 5,
    "nakauwaw": 6,
}

_INTERVENTION_PHRASES = {
    "Referred to Emergency Room": "nag-refer sa emergency room",
    "Referred to Guidance Counselors": "nag-refer sa guidance counselor",
    "Refused Referrals": "wala modawat sa referral",
    "Others": "naghatag og laing assistance",
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
    return text.find(normalized_cue)


def _first_match(text: str, rules: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    normalized = _normalize(text)
    if not normalized:
        return ""
    best: tuple[int, int, str] | None = None
    for order, (label, cues) in enumerate(rules):
        positions = [
            position
            for cue in cues
            if (position := _position(normalized, cue)) >= 0
        ]
        if not positions:
            continue
        item = (min(positions), order, label)
        if best is None or item < best:
            best = item
    return best[2] if best else ""


def _symptom_phrases(
    text: str, limit: int, preferred_text: str | None = None
) -> list[str]:
    normalized = _normalize(text)
    if not normalized:
        return []
    preferred = _normalize(preferred_text or "")
    matches: list[tuple[int, int, int, int, str]] = []
    denies_suicide = bool(_SUICIDE_DENIAL.search(normalized))
    for order, (phrase, cues) in enumerate(_SYMPTOM_RULES):
        if phrase == _PASSIVE_DEATH_WISH and denies_suicide:
            continue
        positions = [
            position
            for cue in cues
            if (position := _position(normalized, cue)) >= 0
        ]
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
    referral_objects: list[str] = []
    if "Given Referrals" in labels and "Referred to Guidance Counselors" not in labels:
        referral_objects.append("referral")
    if "Psychoeducation" in labels:
        referral_objects.append("psychoeducation")
    if referral_objects:
        parts.append(f"naghatag og {_join_phrases(referral_objects)}")

    for label in labels:
        if label in {"Given Referrals", "Psychoeducation"}:
            continue
        phrase = _INTERVENTION_PHRASES.get(label)
        if phrase:
            parts.append(phrase)

    return _join_phrases(parts) if parts else _FALLBACK_INTERVENTION


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
    symptoms = _symptom_phrase(caller_text, max_symptoms, summary_text)
    risk = _risk_phrase(risk_assessment)
    intervention = _intervention_phrase(intervention_categories)
    return "\n".join(
        (
            f"Nitawag ang caller tungod sa {reason}.",
            f"Gipadayag niya nga {symptoms}.",
            f"Sa risk assessment, {risk}.",
            f"Ang counselor {intervention}.",
        )
    )
