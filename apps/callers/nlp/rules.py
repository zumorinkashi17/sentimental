"""Rule-based entity extraction for Cebuano/English call transcripts.

The lexicon lives in ``data/dictionary.json`` so it can be edited without
touching code. This module provides the rule-based half of the hybrid
extractor; :mod:`apps.callers.nlp.ner` provides the trained NER half.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
DICTIONARY_PATH = DATA_DIR / "dictionary.json"

TITLES = r"(?:sir|ma'?am|maam|miss|kuya|ate|boss|doc)"
_NAME_TOKEN = r"(?-i:[A-Z][A-Za-z'’\-]{1,})"
NAME_PATTERN = rf"{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,2}}"

# Small built-in fallback so the app still works before the full dictionary
# file is added. The JSON lexicon overrides/extends these entries.
FALLBACK_DICTIONARY = {
    "name": {"patterns": []},
    "age": {"patterns": [], "number_variations": []},
    "gender": {
        "values": {
            "Male": "Male",
            "Lalaki": "Male",
            "Laki": "Male",
            "Female": "Female",
            "Babaye": "Female",
            "Babae": "Female",
            "Bayot": "LGBTQ+",
            "Tomboy": "LGBTQ+",
            "Bisexual": "LGBTQ+",
            "Trans": "LGBTQ+",
        }
    },
    "civil_status": {
        "values": {
            "Single": "Single",
            "Married": "Married",
            "Minyo": "Married",
            "Separated": "Separated",
            "Nagbulag": "Separated",
            "Widowed": "Widowed",
            "Biyuda": "Widowed",
            "Biyudo": "Widowed",
            "Annulled": "Annulled",
        }
    },
    "location": {
        "values": {
            "Cebu City": "Cebu City",
            "Mandaue": "Mandaue City",
            "Lapu-Lapu": "Lapu-Lapu City",
            "Talisay": "Talisay City",
            "Minglanilla": "Minglanilla",
            "Consolacion": "Consolacion",
        }
    },
}

# Aliases seen in the annotated corpus that are not explicit in the lexicon.
LOCATION_ALIASES = {
    "cebu": "Cebu City",
    "lapulapu": "Lapu-Lapu City",
    "lapu lapu": "Lapu-Lapu City",
    "mandaue": "Mandaue City",
    "talisay": "Talisay City",
    "naga": "Naga City",
    "danao": "Danao City",
    "carcar": "Carcar City",
    "toledo": "Toledo City",
    "bogo": "Bogo City",
}

_NON_NAMES = {
    "single",
    "married",
    "male",
    "female",
    "lalaki",
    "babaye",
    "babae",
    "sir",
    "ma'am",
    "maam",
    "miss",
    "kuya",
    "ate",
    "cebu",
    "cebu city",
    "dili",
    "di",
    "wala",
    "oo",
    "uyab",
    "ang",
    "ako",
    "siya",
    "pero",
    "gusto",
    "tawga",
    "naa",
    "diri",
    "dinhi",
    "didto",
    "diha",
    "ayaw",
    "please",
    "palihug",
    "salamat",
    "unsa",
    "ngano",
    "pwede",
    "sorry",
    "mao",
    "unya",
    "karon",
    "pag",
    "sa",
    "si",
    "ug",
    "og",
    "kay",
    "ni",
    "ikaw",
    "kami",
    "mi",
    "mo",
    "ka",
    "ko",
    "ra",
    "lang",
    "man",
    "gud",
    "gyud",
    "kaayo",
    "na",
    "pa",
    "naay",
    "duna",
    "aduna",
    "asa",
    "taga",
    "nagpuyo",
    "nag-abang",
    "nag-inusara",
    "nag-work",
    "nag-eskwela",
    "estudyante",
    "student",
    "college",
    "years",
    "old",
    "anyos",
    "edad",
    "minyo",
    "bayot",
    "tomboy",
    "trans",
    "gay",
    "bisexual",
    "bi",
    "basak",
    "carreta",
    "fuente",
    "siyudad",
    "nagsugod",
    "gisuwayan",
    "nahadlok",
    "kapoy",
    "kamingaw",
    "mingaw",
    "blangko",
    "bug-at",
    "gana",
    "mabuhi",
    "nawad-an",
    "lami",
    "sige",
    "para",
    "basin",
    "apil",
    "bilib",
    "ipadayon",
    "amping",
    "maayo",
    "hello",
    "grabe",
    "murag",
    "unya",
    "adlaw-adlaw",
    "mobuto",
    "magunitan",
    "gipaningot",
    "nagkurog",
    "makatilaw",
    "sakit",
    "nikalit",
    "nadawat",
    "nagsuka",
    "nanikig",
    "gikulbaan",
    "nahugno",
    "nasabtan",
    "valid",
    "bug-at",
    "grabeha",
    "take",
    "deep",
    "breath",
    "breathing",
    "focus",
    "inhale",
    "exhale",
    "tuition",
    "scholarship",
    "grades",
    "subject",
    "parents",
    "mama",
    "email",
    "bintana",
    "kwarto",
    "cr",
    "guidance",
    "counselor",
    "office",
    "affairs",
    "school",
}


def _normalise_quotes(value: str) -> str:
    return (
        str(value)
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )


def _clean_term(value: str) -> str:
    value = _normalise_quotes(value).strip()
    value = value.strip(" .,!?;:\"'")
    value = re.sub(r"\s+", " ", value)
    return value


@lru_cache(maxsize=1)
def load_dictionary() -> dict:
    """Load the lexicon, falling back to the small built-in dictionary."""
    dictionary = json.loads(json.dumps(FALLBACK_DICTIONARY))
    try:
        with DICTIONARY_PATH.open(encoding="utf-8-sig") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError):
        return dictionary

    if not isinstance(loaded, dict):
        return dictionary

    for section, content in loaded.items():
        if not isinstance(content, dict):
            continue
        target = dictionary.setdefault(section, {})
        if isinstance(target, dict):
            for key, value in content.items():
                if isinstance(value, dict) and isinstance(target.get(key), dict):
                    target[key].update(value)
                elif isinstance(value, list) and isinstance(target.get(key), list):
                    target[key] = list(dict.fromkeys([*target[key], *value]))
                else:
                    target[key] = value
        else:
            dictionary[section] = content
    return dictionary


def _phrase_regex(phrase: str) -> str:
    """Turn a lexicon phrase into a tolerant, case-insensitive regex."""
    phrase = _normalise_quotes(phrase).strip()
    phrase = re.sub(r"\[TITLE\]", " __TITLE__ ", phrase, flags=re.IGNORECASE)
    tokens = [token for token in re.split(r"[\s\-]+", phrase) if token]
    escaped = []
    for token in tokens:
        if token == "__TITLE__":
            escaped.append(TITLES)
        else:
            token = token.replace("'", "['’]?")
            escaped.append(re.escape(token))
    body = r"[\s\-]+".join(escaped)
    return re.compile(rf"\b{body}\b", re.IGNORECASE)


def _term_index(values: dict, *, skip=()) -> list[tuple[str, re.Pattern, str]]:
    """Compile ``{phrase: canonical}`` into longest-first match rules."""
    rules = []
    for phrase, canonical in values.items():
        cleaned = _clean_term(phrase)
        if not cleaned or cleaned.lower() in skip:
            continue
        rules.append((cleaned.lower(), _phrase_regex(cleaned), canonical))
    rules.sort(key=lambda item: len(item[0]), reverse=True)
    return rules


@lru_cache(maxsize=1)
def _gender_rules():
    return _term_index(load_dictionary().get("gender", {}).get("values", {}))


@lru_cache(maxsize=1)
def _civil_status_rules():
    return _term_index(load_dictionary().get("civil_status", {}).get("values", {}))


@lru_cache(maxsize=1)
def _location_rules():
    values = dict(load_dictionary().get("location", {}).get("values", {}))
    values.update({alias: canonical for alias, canonical in LOCATION_ALIASES.items()})
    values.pop("City/Municipality names", None)
    return _term_index(values)


_LOCATION_CUE = re.compile(
    r"(?:^|[\s,;.!?\-])(?:sa|taga|diri|dinhi|didto|diha|dapit|"
    r"nagpuyo|nag-abang|nag-board|nag-stay|located|live|living|from)"
    r"\s*(?:(?:in|at|near|sa|among|akong)\s+)?(?:[,.!?\-]\s*)?$",
    re.IGNORECASE,
)

_PLACE_SUFFIX = re.compile(
    r"\b(?:city|municipality|province|barangay|brgy|sitio|purok|subdivision|"
    r"street|st|avenue|ave|road|rd|drive|village|district|town)\b",
    re.IGNORECASE,
)


def _add_number_word(table: dict[str, int], phrase: str, value: int) -> None:
    table[re.sub(r"\s+", " ", _normalise_quotes(phrase).lower()).strip()] = value


def _age_word_table() -> dict[str, int]:
    table: dict[str, int] = {}

    english_teens = {
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
    }
    for word, value in english_teens.items():
        _add_number_word(table, word, value)
    for base, start in (
        ("twenty", 20),
        ("thirty", 30),
        ("forty", 40),
        ("fifty", 50),
        ("sixty", 60),
    ):
        _add_number_word(table, base, start)
        for offset, unit in enumerate(
            ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine"), 1
        ):
            _add_number_word(table, f"{base}-{unit}", start + offset)

    bisaya_teens = {
        "napulo": 10,
        "napulog-usa": 11,
        "napulog-duha": 12,
        "napulog-tulo": 13,
        "napulog-upat": 14,
        "napulog-lima": 15,
        "napulog-unom": 16,
        "napulog-pito": 17,
        "napulog-walo": 18,
        "napulog-siyam": 19,
    }
    for word, value in bisaya_teens.items():
        _add_number_word(table, word, value)
    for base, start in (
        ("baynte", 20),
        ("traynta", 30),
        ("kwarenta", 40),
        ("singkwenta", 50),
        ("sitenta", 60),
    ):
        _add_number_word(table, base, start)
        for offset, unit in enumerate(
            ("uno", "dos", "tres", "kwatro", "singko", "sais", "syete", "otso", "nuwebe"), 1
        ):
            _add_number_word(table, f"{base} {unit}", start + offset)
            _add_number_word(table, f"{base}-{unit}", start + offset)
            _add_number_word(table, f"{base}'y {unit}", start + offset)
            _add_number_word(table, f"{base}y {unit}", start + offset)

    spanish = {
        "diez": 10,
        "once": 11,
        "doce": 12,
        "trece": 13,
        "catorce": 14,
        "quince": 15,
        "dieciseis": 16,
        "diecisiete": 17,
        "dieciocho": 18,
        "diecinueve": 19,
        "veinte": 20,
        "treinta": 30,
        "cuarenta": 40,
        "cincuenta": 50,
        "sesenta": 60,
    }
    for word, value in spanish.items():
        _add_number_word(table, word, value)
    for base, start in (
        ("veinte", 20),
        ("treinta", 30),
        ("cuarenta", 40),
        ("cincuenta", 50),
    ):
        for offset, unit in enumerate(
            ("uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"), 1
        ):
            _add_number_word(table, f"{base} y {unit}", start + offset)
            if base == "veinte":
                _add_number_word(table, f"veinti{unit}", start + offset)
    return table


@lru_cache(maxsize=1)
def _age_word_rules() -> list[tuple[str, re.Pattern, int]]:
    table = _age_word_table()
    rules = []
    for phrase, value in table.items():
        rules.append((phrase, _phrase_regex(phrase), value))
    rules.sort(key=lambda item: len(item[0]), reverse=True)
    return rules


_AGE_CONTEXT = re.compile(
    r"(anyos|edad|years?\s*old|na\s+ko|pa\s+ko|nako|na\s+mi|pa\s+mi|"
    r"mag-|tungtong|pangedaron|age)",
    re.IGNORECASE,
)
_AGE_EXCLUDE_BEFORE = re.compile(
    r"(grade|level|floor|month|minute|hour|week|day|peso|php|₱|#|no\.?)\s*$",
    re.IGNORECASE,
)
_AGE_EXCLUDE_AFTER = re.compile(
    r"^\s*(?:%|percent|pesos?|php|kg|cm|km|minutes?|hours?|days?|weeks?|months?|"
    r"years?\s+ago)",
    re.IGNORECASE,
)
_YEAR = re.compile(r"^(?:19|20)\d{2}$")


def _entity(label: str, text: str, start: int, end: int, value, confidence: float, source: str):
    return {
        "label": label,
        "text": text[start:end],
        "start": start,
        "end": end,
        "value": value,
        "confidence": round(confidence, 3),
        "source": source,
    }


def _dedupe_overlaps(entities: list[dict]) -> list[dict]:
    """Drop duplicate or covered spans, keeping the strongest match."""
    kept: list[dict] = []
    for entity in sorted(
        entities,
        key=lambda item: (
            item["start"],
            -(item["end"] - item["start"]),
            -item["confidence"],
        ),
    ):
        covered = any(
            other["label"] == entity["label"]
            and other["start"] <= entity["start"]
            and other["end"] >= entity["end"]
            and (other["end"] - other["start"]) >= (entity["end"] - entity["start"])
            for other in kept
        )
        if not covered:
            kept.append(entity)
    return kept


def _extract_ages(text: str) -> list[dict]:
    entities: list[dict] = []
    used: list[tuple[int, int]] = []

    for match in re.finditer(r"\b(\d{1,3})\b", text):
        raw = match.group(1)
        value = int(raw)
        if not 1 <= value <= 99 or _YEAR.match(raw):
            continue
        before = text[max(0, match.start() - 18) : match.start()]
        after = text[match.end() : match.end() + 18]
        if _AGE_EXCLUDE_BEFORE.search(before) or _AGE_EXCLUDE_AFTER.search(after):
            continue
        if before.endswith(":") or after.startswith(":"):
            continue
        has_context = bool(_AGE_CONTEXT.search(before) or _AGE_CONTEXT.search(after))
        if value < 10 and not has_context:
            continue
        confidence = 0.96 if has_context else 0.72
        entities.append(_entity("AGE", text, match.start(), match.end(), value, confidence, "rule"))
        used.append((match.start(), match.end()))

    for _, regex, value in _age_word_rules():
        for match in regex.finditer(text):
            if any(start <= match.start() and match.end() <= end for start, end in used):
                continue
            before = text[max(0, match.start() - 18) : match.start()]
            after = text[match.end() : match.end() + 18]
            if _AGE_EXCLUDE_BEFORE.search(before) or _AGE_EXCLUDE_AFTER.search(after):
                continue
            has_context = bool(_AGE_CONTEXT.search(before) or _AGE_CONTEXT.search(after))
            confidence = 0.94 if has_context else 0.68
            entities.append(
                _entity("AGE", text, match.start(), match.end(), value, confidence, "rule")
            )
            used.append((match.start(), match.end()))

    return _dedupe_overlaps(entities)


_NEGATED_STATUS = re.compile(
    r"\b(?:wala|dili|di)\s+(?:pa\s+)?(?:mi|ko|kami|sila|siya)?\s*$",
    re.IGNORECASE,
)


def _extract_terms(text: str, rules, label: str, confidence: float) -> list[dict]:
    entities: list[dict] = []
    for _, regex, canonical in rules:
        for match in regex.finditer(text):
            if label == "CIVIL_STATUS":
                before = text[max(0, match.start() - 24) : match.start()]
                if _NEGATED_STATUS.search(before):
                    continue
            if label == "LOCATION":
                before = text[max(0, match.start() - 40) : match.start()]
                if not _PLACE_SUFFIX.search(match.group(0)) and not _LOCATION_CUE.search(
                    before
                ):
                    continue
            entities.append(
                _entity(
                    label,
                    text,
                    match.start(),
                    match.end(),
                    canonical,
                    confidence,
                    "rule",
                )
            )
    return _dedupe_overlaps(entities)


def _name_patterns() -> list[tuple[re.Pattern, float]]:
    patterns: list[tuple[str, float]] = [
        (rf"(?m)^\s*({NAME_PATTERN})\s*(?:[.,!?]|$)", 0.8),
        (rf"\b(?:my|the)\s+name\s+is\s+({NAME_PATTERN})\b", 0.95),
        (rf"\b(?:akong|ang)\s+(?:ngalan|name|pangalan)\s+(?:is|mao\s+si)\s+({NAME_PATTERN})\b", 0.94),
        (rf"\bako(?:\s+diay)?\s+si\s+({NAME_PATTERN})\b", 0.95),
        (rf"\bsi\s+({NAME_PATTERN})\s+(?:ko|diay|ni)\b", 0.93),
        (rf"\b(?:i'?m|i\s+am|just\s+call\s+me|you\s+can\s+call\s+me|call\s+me)\s+({NAME_PATTERN})\b", 0.93),
        (
            rf"\btawga(?:\s+lang)?\s+(?:ko|kog|ko'g|nako)\s+(?:og|ug|'g)?\s*[\"']?({NAME_PATTERN})",
            0.93,
        ),
        (
            rf"\btawga(?:\s+lang)?\s+(?:ko|kog|ko'g|nako)\s+(?:og|ug|'g)?\s*[\"']?"
            rf"([A-Za-z][A-Za-z'’\-]*)",
            0.9,
        ),
        (rf"\b((?-i:([A-Z]))-(?-i:\2)[A-Za-z'’\-]+)\b", 0.88),
        (
            rf"\b({NAME_PATTERN})\s+(?:lang|ra)\s+"
            rf"(?:ko|kami|mi|akong|ang|name|ngalan|pangalan|palayaw)\b",
            0.84,
        ),
        (rf"\b({NAME_PATTERN})\s+(?:akong|ang)\s+(?:ngalan|name|pangalan|palayaw)\b", 0.94),
        (
            rf"\b(?:akong|ang)\s+(?:ngalan|name|pangalan)\s+(?:kay|nako\s+kay)\s+({NAME_PATTERN})\b",
            0.94,
        ),
        (
            rf"\b(?:ang\s+tawag|tigtawag)\s+(?:nila\s+)?nako\s+(?:kay|og|'g)\s+({NAME_PATTERN})\b",
            0.92,
        ),
        (rf"\b({NAME_PATTERN})\s+diay\b", 0.88),
        (rf"\b({NAME_PATTERN})\s+na\s+lang\b", 0.84),
    ]
    return [(re.compile(pattern, re.IGNORECASE), confidence) for pattern, confidence in patterns]


def _dictionary_name_patterns() -> list[tuple[re.Pattern, float]]:
    patterns = load_dictionary().get("name", {}).get("patterns", [])
    compiled: list[tuple[re.Pattern, float]] = []
    for pattern in patterns:
        if not isinstance(pattern, str) or "[NAME]" not in pattern:
            continue
        template = _normalise_quotes(pattern).strip().strip("\"'").rstrip(".,;:")
        if not re.search(r"[A-Za-z]", template.replace("[NAME]", "").replace("[NICKNAME]", "")):
            # Pure `[NAME].`-style patterns are too broad; the anchored
            # first-token rule handles them with a lexicon filter.
            continue
        template = re.sub(r"\[TITLE\]", "__TITLE__", template, flags=re.IGNORECASE)
        template = template.replace("[NICKNAME]", "[NAME]")
        parts = re.split(r"(\[NAME\])", template)
        regex_parts = []
        for part in parts:
            if part == "[NAME]":
                regex_parts.append(f"({NAME_PATTERN})")
                continue
            for chunk in re.split(r"(__TITLE__)", part):
                if chunk == "__TITLE__":
                    regex_parts.append(TITLES)
                elif chunk:
                    regex_parts.append(re.sub(r"\\ ", r"\\s+", re.escape(chunk)))
        # Dictionary entries are full utterances. Without a boundary, a short
        # template such as "[NAME] lang." also matches "Sakit lang gyud ...".
        regex_parts.append(r"(?=\s*(?:[.,!?;:]|$))")
        compiled.append((re.compile("".join(regex_parts), re.IGNORECASE), 0.9))
    return compiled


def _clean_name(value: str) -> str:
    value = _normalise_quotes(value).strip().strip(" .,!?;:\"'")
    value = re.sub(r"^(?:si|og|ug|kay|ko'g|kog)\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^([A-Za-z])-\1", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value)
    return value


@lru_cache(maxsize=1)
def _non_name_terms() -> frozenset[str]:
    terms = set(_NON_NAMES)
    for section in ("gender", "civil_status", "location"):
        for phrase in load_dictionary().get(section, {}).get("values", {}):
            cleaned = _clean_term(phrase).lower()
            if cleaned:
                terms.add(cleaned)
    terms.update(alias.lower() for alias in LOCATION_ALIASES)
    terms.update(_age_word_table().keys())
    return frozenset(terms)


def _looks_like_name(value: str) -> bool:
    cleaned = _clean_term(value)
    if not cleaned or re.search(r"\d", cleaned):
        return False
    if len(cleaned) == 1 and not cleaned.isupper():
        return False
    lowered = cleaned.lower()
    if lowered in _non_name_terms():
        return False
    first = lowered.split()[0]
    return first not in _non_name_terms()


def _extract_names(text: str) -> list[dict]:
    entities: list[dict] = []
    for regex, confidence in [*_name_patterns(), *_dictionary_name_patterns()]:
        for match in regex.finditer(text):
            name = _clean_name(match.group(1))
            if not _looks_like_name(name):
                continue
            start, end = match.span(1)
            entities.append(_entity("NAME", text, start, end, name, confidence, "rule"))
    return _dedupe_overlaps(entities)


_TRANSCRIPT_HEADER = re.compile(
    r"^-+\s*Sentimental Conversation Transcript\s*-+\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_PHASE_HEADER = re.compile(
    r"^\s*\[?\s*PHASE\s+\d+\b[^\]]*\]?\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_SPEAKER_LINE = re.compile(
    r"^\s*(?:\[)?(caller|responder|client|agent|user|assistant)(?:\])?\s*:\s*(.*)$",
    re.IGNORECASE,
)
_BRACKET_SPEAKER = re.compile(
    r"^\s*\[(caller|responder|client|agent|user|assistant)\]\s*(.*)$",
    re.IGNORECASE,
)


def _speaker_role(label: str) -> str:
    return "caller" if label.lower() in {"caller", "client", "user"} else "responder"


def _strip_speaker_labels(text: str) -> str:
    lines = []
    for line in text.splitlines():
        match = _SPEAKER_LINE.match(line) or _BRACKET_SPEAKER.match(line)
        if match:
            lines.append(match.group(2))
        else:
            lines.append(line)
    return "\n".join(lines)


def _extract_speaker_text(text: str, wanted_role: str) -> str:
    raw = str(text or "")
    raw = _TRANSCRIPT_HEADER.sub("", raw)
    raw = _PHASE_HEADER.sub("", raw)
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")

    turns: list[str] = []
    current: str | None = None
    buffer: list[str] = []
    found = False

    def flush() -> None:
        if current == wanted_role:
            chunk = "\n".join(buffer).strip()
            if chunk:
                turns.append(chunk)

    for line in raw.splitlines():
        match = _SPEAKER_LINE.match(line) or _BRACKET_SPEAKER.match(line)
        if match:
            flush()
            buffer = []
            current = _speaker_role(match.group(1))
            found = True
            rest = match.group(2).strip()
            if rest:
                buffer.append(rest)
            continue
        if current is not None:
            buffer.append(line)
    flush()

    if not found:
        return clean_text(text)
    return clean_text("\n".join(turns))


def extract_caller_text(text: str) -> str:
    """Return only the caller's turns when speaker labels are present."""
    return _extract_speaker_text(text, "caller")


def extract_responder_text(text: str) -> str:
    """Return only the responder's turns when speaker labels are present."""
    return _extract_speaker_text(text, "responder")


def clean_text(text: str) -> str:
    """Remove transcript chrome so offsets map to the analysed text."""
    text = str(text or "")
    text = _TRANSCRIPT_HEADER.sub("", text)
    text = _PHASE_HEADER.sub("", text)
    text = _strip_speaker_labels(text)
    text = re.sub(r"\[(?:Caller|Responder)\]\s*", "", text, flags=re.IGNORECASE)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def extract_rules(text: str) -> list[dict]:
    """Run every rule-based extractor and return all candidate entities."""
    entities: list[dict] = []
    entities.extend(_extract_names(text))
    entities.extend(_extract_ages(text))
    entities.extend(_extract_terms(text, _gender_rules(), "GENDER", 0.9))
    entities.extend(_extract_terms(text, _civil_status_rules(), "CIVIL_STATUS", 0.88))
    entities.extend(_extract_terms(text, _location_rules(), "LOCATION", 0.92))
    return entities


def canonical_gender(value: str) -> str | None:
    value = _clean_term(value)
    for _, regex, canonical in _gender_rules():
        if regex.search(value):
            return canonical
    return None


_HUSBAND_REFERENCE = re.compile(
    r"\b(?:akong\s+bana|bana\s+(?:nako|ko|namo))\b",
    re.IGNORECASE,
)
_WIFE_REFERENCE = re.compile(
    r"\b(?:akong\s+asawa|asawa\s+(?:nako|ko|namo))\b",
    re.IGNORECASE,
)


def infer_gender_from_context(text: str) -> str | None:
    """Infer gender only from an explicit spouse reference."""
    value = _clean_term(str(text or ""))
    if _HUSBAND_REFERENCE.search(value):
        return "Female"
    if _WIFE_REFERENCE.search(value):
        return "Male"
    return None


def canonical_civil_status(value: str) -> str | None:
    value = _clean_term(value)
    for _, regex, canonical in _civil_status_rules():
        if regex.search(value):
            return canonical
    return None


def canonical_location(value: str) -> str:
    value = _clean_term(value)
    for _, regex, canonical in _location_rules():
        if regex.search(value):
            return canonical
    return value


def is_known_location(value: str) -> bool:
    value = _clean_term(value)
    return any(regex.search(value) for _, regex, _ in _location_rules())


def is_name_candidate(value: str) -> bool:
    return _looks_like_name(value)


def parse_age(value: str) -> int | None:
    value = _clean_term(value)
    if not value:
        return None
    digits = re.search(r"\b(\d{1,3})\b", value)
    if digits:
        number = int(digits.group(1))
        return number if 1 <= number <= 99 else None
    for _, regex, number in _age_word_rules():
        if regex.search(value):
            return number
    return None
