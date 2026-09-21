import logging
from typing import Any

from domain.narrative_rules import MIN_COMPETENCIES, level_from_score, normalize_benchmark_level

logger = logging.getLogger(__name__)


class ScoreDocumentBuilder:
    """Turns the raw assessment payload into the normalized competency list the
    workflow consumes: validates shape, fills in missing levels, and enforces the
    minimum competency count."""

    def build_competencies(self, assessment: dict[str, Any]) -> list[dict[str, Any]]:
        logger.debug(
            "assessment_name=%s has_competencies=%s keys=%s",
            assessment.get("assessment_name"),
            "competencies" in assessment,
            sorted(assessment.keys()),
        )

        raw_competencies = assessment["competencies"]
        if not isinstance(raw_competencies, list):
            raise ValueError(f"Invalid competencies type: {type(raw_competencies).__name__}")

        competencies = [self._build_one(idx, comp) for idx, comp in enumerate(raw_competencies)]

        if len(competencies) < MIN_COMPETENCIES:
            raise ValueError(
                f"Assessment has {len(competencies)} competencies, "
                f"below minimum required ({MIN_COMPETENCIES})."
            )
        return competencies

    def _build_one(self, index: int, comp: Any) -> dict[str, Any]:
        if not isinstance(comp, dict):
            raise ValueError(f"Invalid competency item at comp idx {index}: {type(comp).__name__}")
        if "competency" not in comp:
            raise ValueError(
                f"Missing 'competency' key at comp idx {index}; keys={sorted(comp.keys())}"
            )

        score_percent = float(comp.get("score_percent", 0.0))
        achieved_level = str(comp.get("achieved_level") or "").strip() or level_from_score(score_percent)
        description = str(comp["description"]).strip() if comp.get("description") else None

        return {
            "competency": comp["competency"],
            "score_percent": score_percent,
            "achieved_level": achieved_level,
            "benchmark_level": normalize_benchmark_level(comp.get("benchmark_level")),
            "gap_percent": comp.get("gap_percent"),
            "description": description,
        }


def get_score_document_builder() -> ScoreDocumentBuilder:
    return ScoreDocumentBuilder()

