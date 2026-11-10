"""Helpers for normalising free-text caller locations and mapping PSGC regions."""

import re

# PSGC region code (9 digits, as returned by the PSGC API) -> the short code
# used by apps.heatmap.views.REGIONS. MIMAROPA uses the legacy 17xxxxxxx block.
PSGC_REGION_CODES = {
    "010000000": "I",
    "020000000": "II",
    "030000000": "III",
    "040000000": "IV-A",
    "170000000": "IV-B",
    "050000000": "V",
    "060000000": "VI",
    "070000000": "VII",
    "080000000": "VIII",
    "090000000": "IX",
    "100000000": "X",
    "110000000": "XI",
    "120000000": "XII",
    "130000000": "NCR",
    "140000000": "CAR",
    "160000000": "XIII",
    "150000000": "BARMM",
}


def normalize_location(value):
    """Lower-case a free-text location and strip noise like "Brgy." prefixes."""
    text = str(value or "").strip().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(barangay|brgy|bgy)\s+", "", text)
    return text


def strip_city_prefix(name):
    """Turn PSGC's "City of Cebu" into "Cebu" for alias matching."""
    text = str(name or "").strip()
    if text.lower().startswith("city of "):
        return text[len("city of "):].strip()
    return text
