from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, Field

from core.settings import Settings, get_settings
from llm_gateway.client import LLMClient, get_llm_client
from prompts.role_prompts import ROLE_GENERATION_SYS, build_role_generation_user_prompt


class RoleGenerationOutput(BaseModel):
    role: str = Field(min_length=1)


class RoleService:
    def __init__(self, llm_client: LLMClient, settings: Settings) -> None:
        self._llm_client = llm_client
        self._settings = settings

    async def generate_role_from_competencies(
        self,
        competencies_by_assessment: dict[str, list[dict[str, str]]],
        organization: str | None,
        examples: str | None = None,
    ) -> tuple[str, list[str]]:
        user_prompt = build_role_generation_user_prompt(
            competencies_by_assessment, organization, examples
        )
        web_search = (
            self._settings.llm_web_search_role_generation
            and self._llm_client.provider_name() == "openai"
        )
        parsed = await self._llm_client.parse(
            system_prompt=ROLE_GENERATION_SYS,
            user_prompt=user_prompt,
            response_format=RoleGenerationOutput,
            temperature=0.1,
            max_tokens=150,
            model=self._settings.primary_model_name(),
            web_search=web_search,
        )
        if parsed.parsed and parsed.parsed.role.strip():
            return parsed.parsed.role.strip(), parsed.sources

        generated = await self._llm_client.generate(
            system_prompt=ROLE_GENERATION_SYS,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=60,
            model=self._settings.primary_model_name(),
            web_search=web_search,
        )
        role = generated.text.strip().splitlines()[0].strip(" \t\"'") if generated.text.strip() else "Not specified"
        return role or "Not specified", generated.sources or []


def get_role_service(
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RoleService:
    return RoleService(llm_client, settings)
