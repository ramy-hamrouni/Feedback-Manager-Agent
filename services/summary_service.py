import logging
import re
from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, Field

from core.settings import Settings, get_settings
from llm_gateway.client import LLMClient, get_llm_client
from prompts.narrative_feedback_prompts import (
    V7_COMP_USER,
    V7_EXEC_SYS,
    V7_EXEC_USER,
    V7_FEEDBACK_SYS,
    facts_to_text,
)


logger = logging.getLogger(__name__)

# Section labels the model sometimes emits despite the format constraint, e.g.
# "Headline: …\n\nClear strength: …". Stripped so the report always gets prose.
_SECTION_LABEL = re.compile(
    r"(?:^|(?<=\n))\s*(?:[-*\u2022]\s*)?(?:\d+[.)]\s*)?"
    r"(?:headline(?:\s+takeaway)?|overall|summary|clear strengths?|strengths?|"
    r"areas? developing well|developing well|priorit(?:y|ies)(?: for development| areas?)?|"
    r"development priorit(?:y|ies)|areas? for development|most urgent(?: development area)?|"
    r"benchmark alignment)\s*:\s*",
    re.IGNORECASE,
)


def _to_single_paragraph(text: str) -> str:
    """Collapse a labelled/bulleted summary into one flowing paragraph."""
    if not text:
        return ""
    cleaned = _SECTION_LABEL.sub(" ", text)
    cleaned = re.sub(r"^\s*[-*\u2022]\s*", " ", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


class ExecutiveSummaryOutput(BaseModel):
    executive_summary: str = Field(
        default="",
        description="90-140 word constructive, manager-facing summary of the assessment results, "
        "referring to the assessed person as 'the employee'. Leads with a one-line "
        "headline takeaway, then groups competencies into strengths, areas developing "
        "well, and priorities for development, flagging the single most urgent gap.",
    )


class CompetencyReportOutput(BaseModel):
    benchmark_position: str = Field(
        default="",
        description="ONE short sentence in the style of the worked examples, e.g. 'Achieved "
        "Foundation, one level below the Applied benchmark' or 'Achieved Advanced, "
        "meeting the Advanced benchmark'. Name the achieved level and (if present) "
        "the benchmark level and state the relationship.",
    )
    interpretation: str = Field(
        default="",
        description="Constructive, manager-facing narrative in the SAME STYLE as the worked "
        "examples: open with 'In the competency of <name>, the employee has "
        "reached/attained a <band> level of proficiency,  then describe in flowing sentences "
        "what the employee demonstrably does at this proficiency and what it enables. Refer to "
        "'the employee' and retain the concrete framework specifics.",
    )


class SummaryService:
    def __init__(self, llm_client: LLMClient, settings: Settings) -> None:
        self._llm_client = llm_client
        self._settings = settings

    async def generate_executive_summary(
        self,
        assessment_name: str,
        strategy_instruction: str,
        competency_table: str,
        organization: str | None = None,
    ) -> str:
        user_prompt = V7_EXEC_USER.format(
            organization=organization or "Not specified",
            assessment_name=assessment_name,
            strategy_instruction=strategy_instruction,
            competency_table=competency_table,
        )
        parsed = await self._llm_client.parse(
            system_prompt=V7_EXEC_SYS,
            user_prompt=user_prompt,
            response_format=ExecutiveSummaryOutput,
            temperature=self._settings.llm_temperature,
            max_tokens=self._settings.llm_max_tokens_summary,
            model=self._settings.primary_model_name(),
            web_search=self._settings.llm_web_search_summary,
        )
        if not parsed.parsed:
            return ""
        raw = parsed.parsed.executive_summary.strip()
        summary = _to_single_paragraph(raw)
        if summary != raw:
            logger.warning(
                "Executive summary came back with section labels/line breaks; "
                "normalized to a single paragraph (%d -> %d chars)",
                len(raw),
                len(summary),
            )
        return summary

    async def generate_interpretation(
        self,
        competency: str,
        result_line: str,
        definition: str,
        level_descriptions: dict[str, str],
        strategy_instruction: str,
        organization: str | None = None,
    ) -> tuple[str, str]:
        """Returns (benchmark_position, interpretation)."""
        user_prompt = V7_COMP_USER.format(
            organization=organization or "Not specified",
            competency=competency,
            result_line=result_line,
            facts=facts_to_text(result_line, definition, level_descriptions),
            strategy_instruction=strategy_instruction,
        )
        parsed = await self._llm_client.parse(
            system_prompt=V7_FEEDBACK_SYS,
            user_prompt=user_prompt,
            response_format=CompetencyReportOutput,
            temperature=self._settings.llm_temperature,
            max_tokens=self._settings.llm_max_tokens_interpretation,
            model=self._settings.primary_model_name(),
            web_search=self._settings.llm_web_search_interpretation,
        )
        if not parsed.parsed:
            return "", ""
        return parsed.parsed.benchmark_position.strip(), parsed.parsed.interpretation.strip()


def get_summary_service(
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SummaryService:
    return SummaryService(llm_client, settings)
