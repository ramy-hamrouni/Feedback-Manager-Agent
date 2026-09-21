import difflib
import html
import re
from typing import Any


MIN_COMPETENCIES = 3
ZERO_LEVEL_LABEL = "No Proficiency Demonstrated"
BAND_MIN = {"Foundation": 0.0, "Applied": 34.0, "Advanced": 67.0}
BENCHMARK_TO_FRAMEWORK = {
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


def normalize_benchmark_level(level: str | None) -> str | None:
    if not level:
        return None
    return BENCHMARK_TO_FRAMEWORK.get(str(level).strip(), str(level).strip())


def strategy_from_competencies(competencies: list[dict[str, Any]]) -> tuple[str, int]:
    benchmarked_count = sum(1 for c in competencies if c.get("benchmark_level"))
    if benchmarked_count == len(competencies):
        return "benchmarked", benchmarked_count
    if benchmarked_count == 0:
        return "unbenchmarked", benchmarked_count
    return "mixed", benchmarked_count


