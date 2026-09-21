from typing import Annotated

from fastapi import Depends

from core.settings import Settings, get_settings
from llm_gateway.client import LLMClient, get_llm_client
from services.framework_service import FrameworkService
from services.role_service import RoleService
from services.summary_service import SummaryService


class NarrativeLLMService:
    def __init__(self, llm_client: LLMClient, settings: Settings) -> None:
        self._summary = SummaryService(llm_client, settings)
        self._role = RoleService(llm_client, settings)
        self._framework = FrameworkService(llm_client, settings)

    async def generate_executive_summary(
        self,
        assessment_name: str,
        strategy_instruction: str,
        competency_table: str,
        organization: str | None = None,
    ) -> str:
        return await self._summary.generate_executive_summary(
            assessment_name=assessment_name,
            strategy_instruction=strategy_instruction,
            competency_table=competency_table,
            organization=organization,
        )

    async def generate_interpretation(
        self,
        competency: str,
        result_line: str,
        definition: str,
        level_descriptions: dict[str, str],
        strategy_instruction: str,
        organization: str | None = None,
    ) -> tuple[str, str]:
        return await self._summary.generate_interpretation(
            competency=competency,
            result_line=result_line,
            definition=definition,
            level_descriptions=level_descriptions,
            strategy_instruction=strategy_instruction,
            organization=organization,
        )

    async def generate_role_from_competencies(
        self,
        competencies_by_assessment: dict[str, list[dict[str, str]]],
        organization: str | None,
        examples: str | None = None,
    ) -> tuple[str, list[str]]:
        return await self._role.generate_role_from_competencies(
            competencies_by_assessment, organization, examples
        )

    async def generate_job_purpose(
        self,
        industry: str,
        seniority: str,
        role: str,
        competencies: list[str],
        organization: str | None,
    ) -> tuple[str, list[str]]:
        return await self._framework.generate_job_purpose(
            industry=industry,
            seniority=seniority,
            role=role,
            competencies=competencies,
            organization=organization,
        )

    async def generate_competency_definition(
        self,
        role: str | None,
        job_purpose: str,
        competency: str,
        organization: str | None,
        example: str | None,
    ) -> tuple[str, list[str]]:
        return await self._framework.generate_competency_definition(
            role=role,
            job_purpose=job_purpose,
            competency=competency,
            organization=organization,
            example=example,
        )

    async def generate_framework_levels(
        self,
        industry: str,
        role: str,
        competency: str,
        definition: str,
        job_purpose: str,
        organization: str | None,
        examples: str = "",
    ) -> tuple[dict[str, str], list[str]]:
        return await self._framework.generate_framework_levels(
            industry=industry,
            role=role,
            competency=competency,
            definition=definition,
            job_purpose=job_purpose,
            organization=organization,
            examples=examples,
        )


def get_narrative_llm_service(
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NarrativeLLMService:
    return NarrativeLLMService(llm_client, settings)
