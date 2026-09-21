import difflib
import html
import re
from typing import Any


MIN_COMPETENCIES = 3
ZERO_LEVEL_LABEL = "No Proficiency Demonstrated"
LEVEL_TO_FRAMEWORK_BAND = {
    "Foundation": "Foundation",
    "Intermediate": "Applied",
    "Applied": "Applied",
    "Advanced": "Advanced",
    "Expert": "Advanced",
}
LEVEL_TO_INT = {"Foundation": 1, "Applied": 2, "Advanced": 3}
DEFAULT_FRAMEWORK_LEVELS = {
    "Foundation": "Performs routine tasks under direct supervision with foundational knowledge.",
    "Applied": "Works independently on non-routine tasks and applies standard procedures effectively.",
    "Advanced": "Handles complex, ambiguous situations with minimal guidance and mentors peers.",
}


def comp_key(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]+", " ", html.unescape(str(name)).lower()).split()
    return "".join(
        w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
        for w in words
    )


def norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def normalize_role(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def role_similarity(role_a: str | None, role_b: str | None) -> float:
    a = normalize_role(role_a)
    b = normalize_role(role_b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def level_from_score(score_percent: float) -> str:
    if score_percent <= 0:
        return ZERO_LEVEL_LABEL
    if score_percent <= 33:
        return "Foundation"
    if score_percent <= 66:
        return "Applied"
    return "Advanced"


def framework_band_for(level: str | None, score_percent: float) -> str:
    """Map a stored/authored level onto the 3-band ladder the framework level
    descriptions are keyed by. This is a LOOKUP KEY, never a label shown to a reader:
    the stored level (e.g. "Expert") is what gets rendered, this is what selects the
    description. An unrecognized level falls back to the score-derived band so the
    lookup can never silently miss."""
    key = str(level or "").strip()
    if key in LEVEL_TO_FRAMEWORK_BAND:
        return LEVEL_TO_FRAMEWORK_BAND[key]
    return level_from_score(score_percent)




