from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, Field

from core.settings import Settings, get_settings
from domain.narrative_rules import DEFAULT_FRAMEWORK_LEVELS
from llm_gateway.client import LLMClient, get_llm_client
from prompts.framework_prompts import (
    JOB_PURPOSE_SYS,
    build_competency_definition_system_prompt,
    build_competency_definition_user_prompt,
    build_job_purpose_user_prompt,
    build_levels_system_prompt,
    build_levels_user_prompt,
)


class JobPurposeOutput(BaseModel):
    job_purpose: str = Field(
        default="", description="Concise, clear job purpose for the role/competency."
    )


class CompetencyDefinitionOutput(BaseModel):
    definition: str = Field(
        default="", description="~50-word competency definition beginning with 'Ability to'."
    )


class ProficiencyLevelsOutput(BaseModel):
    foundation: str = Field(default="")
    applied: str = Field(default="")
    advanced: str = Field(default="")


class FrameworkService:
    def __init__(self, llm_client: LLMClient, settings: Settings) -> None:
        self._llm_client = llm_client
        self._settings = settings

    def _web_search(self, organization: str | None, flag: bool) -> bool:
        return bool(organization) and flag and self._llm_client.provider_name() == "openai"

    async def generate_job_purpose(
        self,
        industry: str,
        seniority: str,
        role: str,
        competencies: list[str],
        organization: str | None,
    ) -> tuple[str, list[str]]:
        use_web_search = self._web_search(
            organization, self._settings.llm_web_search_job_purpose
        )
        parsed = await self._llm_client.parse(
            system_prompt=JOB_PURPOSE_SYS,
            user_prompt=build_job_purpose_user_prompt(
                industry=industry,
                seniority=seniority,
                role=role,
                competencies=competencies,
                organization=organization if use_web_search else None,
            ),
            response_format=JobPurposeOutput,
            temperature=0.2,
            max_tokens=200,
            model=self._settings.framework_jobpurpose_model_name(),
            web_search=use_web_search,
        )
        text = parsed.parsed.job_purpose.strip() if parsed.parsed else ""
        return text, parsed.sources or []

    async def generate_competency_definition(
        self,
        role: str | None,
        job_purpose: str,
        competency: str,
        organization: str | None,
        example: str | None,
    ) -> tuple[str, list[str]]:
        use_web_search = self._web_search(
            organization, self._settings.llm_web_search_competency_definition
        )
        parsed = await self._llm_client.parse(
            system_prompt=build_competency_definition_system_prompt(competency),
            user_prompt=build_competency_definition_user_prompt(
                role=role,
                job_purpose=job_purpose,
                competency=competency,
                organization=organization,
                example=example,
            ),
            response_format=CompetencyDefinitionOutput,
            temperature=0.2,
            max_tokens=200,
            model=self._settings.framework_definition_model_name(),
            web_search=use_web_search,
        )
        text = parsed.parsed.definition.strip() if parsed.parsed else ""
        return text, parsed.sources or []

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
        use_web_search = self._web_search(
            organization, self._settings.llm_web_search_framework_levels
        )
        parsed = await self._llm_client.parse(
            system_prompt=build_levels_system_prompt(
                industry=industry,
                role=role,
                competency=competency,
                definition=definition,
                job_purpose=job_purpose,
                organization=organization if use_web_search else None,
            ),
            user_prompt=build_levels_user_prompt(competency, role, examples),
            response_format=ProficiencyLevelsOutput,
            temperature=0.1,
            max_tokens=1200,
            model=self._settings.framework_proficiency_model_name(),
            web_search=use_web_search,
        )
        if parsed.parsed:
            levels = {
                "Foundation": parsed.parsed.foundation or DEFAULT_FRAMEWORK_LEVELS["Foundation"],
                "Applied": parsed.parsed.applied or DEFAULT_FRAMEWORK_LEVELS["Applied"],
                "Advanced": parsed.parsed.advanced or DEFAULT_FRAMEWORK_LEVELS["Advanced"],
            }
            return levels, parsed.sources or []
        return dict(DEFAULT_FRAMEWORK_LEVELS), parsed.sources or []


def get_framework_service(
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FrameworkService:
    return FrameworkService(llm_client, settings)
