from functools import lru_cache
from typing import Literal

import os

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MANAGER_AGENT_",
        case_sensitive=False,
        extra="ignore",
        env_file=(".env", "api/.env"),
        env_file_encoding="utf-8",
    )

    llm_provider: Literal["mock", "openai", "anthropic"] = Field(
        default="openai",
        validation_alias=AliasChoices("MANAGER_AGENT_LLM_PROVIDER", "PROVIDER"),
    )

    # Generic model fallback used when provider-specific model is not configured.
    llm_model: str = Field(
        default="gpt-5.4",
        validation_alias=AliasChoices("MANAGER_AGENT_LLM_MODEL", "LLM_MODEL"),
    )
    openai_model: str = Field(
        default="gpt-5.4",
        validation_alias=AliasChoices("MANAGER_AGENT_OPENAI_MODEL", "OPENAI_MODEL"),
    )
    small_openai_model: str = Field(
        default="gpt-5.4-mini",
        validation_alias=AliasChoices("MANAGER_AGENT_SMALL_OPENAI_MODEL", "SMALL_OPENAI_MODEL"),
    )
    anthropic_model: str = Field(
        default="claude-sonnet-4-6",
        validation_alias=AliasChoices("MANAGER_AGENT_ANTHROPIC_MODEL", "ANTHROPIC_MODEL"),
    )

    llm_temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        validation_alias=AliasChoices("MANAGER_AGENT_LLM_TEMPERATURE", "TEMPERATURE"),
    )
    llm_max_tokens_summary: int = Field(default=400, ge=32)
    llm_max_tokens_interpretation: int = Field(default=2000, ge=32)
    llm_timeout_seconds: float = Field(default=20.0, gt=0.0)
    llm_fallback_to_rules: bool = True
    llm_web_search_summary: bool = False
    llm_web_search_interpretation: bool = False
    llm_web_search_role_generation: bool = True
    llm_web_search_job_purpose: bool = True
    llm_web_search_competency_definition: bool = True
    llm_web_search_framework_levels: bool = True

    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MANAGER_AGENT_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MANAGER_AGENT_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )

    enrich_with_framework: bool = Field(
        default=True,
        validation_alias=AliasChoices("MANAGER_AGENT_ENRICH_WITH_FRAMEWORK", "ENRICH_WITH_FRAMEWORK"),
    )
    framework_jobpurpose_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MANAGER_AGENT_FRAMEWORK_JOBPURPOSE_MODEL", "FRAMEWORK_JOBPURPOSE_MODEL"),
    )
    framework_definition_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MANAGER_AGENT_FRAMEWORK_DEFINITION_MODEL", "FRAMEWORK_DEFINITION_MODEL"),
    )
    framework_proficiency_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MANAGER_AGENT_FRAMEWORK_PROFICIENCY_MODEL", "FRAMEWORK_PROFICIENCY_MODEL"),
    )

    langfuse_secret_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MANAGER_AGENT_LANGFUSE_SECRET_KEY", "LANGFUSE_SECRET_KEY"),
    )
    langfuse_public_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MANAGER_AGENT_LANGFUSE_PUBLIC_KEY", "LANGFUSE_PUBLIC_KEY"),
    )
    langfuse_host: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MANAGER_AGENT_LANGFUSE_HOST", "LANGFUSE_HOST"),
    )

    artifact_bucket_uri: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "MANAGER_AGENT_ARTIFACT_BUCKET_URI",
            "TARGET_BUCKET_URI",
            "ARTIFACT_BUCKET_URI",
        ),
    )
    artifact_release_version: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "MANAGER_AGENT_ARTIFACT_RELEASE_VERSION",
            "RELEASE_VERSION",
            "ARTIFACT_RELEASE_VERSION",
        ),
    )
    artifact_local_cache_dir: str = ".cache/manager_agent_artifacts"
    azure_storage_connection_string: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "MANAGER_AGENT_AZURE_STORAGE_CONNECTION_STRING",
            "AZURE_CONNECTION_STRING",
            "AZURE_STORAGE_CONNECTION_STRING",
            "JD_STORAGE_AZURELINK",
        ),
    )
    run_storage_prefix: str = Field(
        default="runs",
        validation_alias=AliasChoices("MANAGER_AGENT_RUN_STORAGE_PREFIX", "RUN_STORAGE_PREFIX"),
    )
    persist_runs_to_storage: bool = Field(
        default=True,
        validation_alias=AliasChoices("MANAGER_AGENT_PERSIST_RUNS_TO_STORAGE", "PERSIST_RUNS_TO_STORAGE"),
    )

    # Score-id-driven input: MongoDB (scores / competencies / projects).
    # One cluster per deployment, selected by MANAGER_AGENT_MONGO_REGION (UAE | KSA | DEV).
    mongo_username: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MANAGER_AGENT_MONGO_USERNAME", "CB_MONGO_USER"),
    )
    mongo_password: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MANAGER_AGENT_MONGO_PASSWORD", "CB_MONGO_PASS"),
    )
    mongo_db_name: str = Field(
        default="smart-recruitement-prod",
        validation_alias=AliasChoices("MANAGER_AGENT_MONGO_DB_NAME", "MONGO_DB_NAME"),
    )
    mongo_dev_db_name: str = Field(
        default="smart-recruitement-dev",
        validation_alias=AliasChoices("MANAGER_AGENT_MONGO_DEV_DB_NAME", "MONGO_DEV_DB_NAME"),
    )
    mongo_region: Literal["UAE", "KSA", "DEV"] = Field(
        default="DEV",
        validation_alias=AliasChoices("MANAGER_AGENT_MONGO_REGION", "MONGO_REGION"),
    )
    mongo_uae_host: str = Field(
        default="cb-common-prod.ezdqj.mongodb.net",
        validation_alias=AliasChoices("MANAGER_AGENT_MONGO_UAE_HOST", "MONGO_UAE_HOST"),
    )
    mongo_ksa_host: str = Field(
        default="cb-common-prod-ksa-1.ezdqj.mongodb.net",
        validation_alias=AliasChoices("MANAGER_AGENT_MONGO_KSA_HOST", "MONGO_KSA_HOST"),
    )
    mongo_server_selection_timeout_ms: int = Field(default=8000, gt=0)
    mongo_dev_uri: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MANAGER_AGENT_MONGO_DEV_URI", "CB_MONGO_DEV_URI"),
    )

    log_level: str = Field(
        default="INFO",
        validation_alias=AliasChoices("MANAGER_AGENT_LOG_LEVEL", "LOG_LEVEL"),
    )

    @field_validator("llm_provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: str | None) -> str:
        return str(value or "openai").strip().lower()

    @field_validator("mongo_region", mode="before")
    @classmethod
    def _normalize_mongo_region(cls, value: str | None) -> str:
        return str(value or "DEV").strip().upper()

    @field_validator("run_storage_prefix", mode="before")
    @classmethod
    def _normalize_run_storage_prefix(cls, value: str | None) -> str:
        prefix = str(value or "runs").strip().strip("/")
        return prefix or "runs"

    def primary_model_name(self) -> str:
        if self.llm_provider == "openai":
            return (self.openai_model or self.llm_model).strip()
        if self.llm_provider == "anthropic":
            return (self.anthropic_model or self.llm_model).strip()
        return (self.llm_model or "mock-model").strip()

    def small_model_name(self) -> str:
        if self.llm_provider == "openai":
            return (self.small_openai_model or self.openai_model or self.llm_model).strip()
        return self.primary_model_name()

    def framework_jobpurpose_model_name(self) -> str:
        return (self.framework_jobpurpose_model or self.primary_model_name()).strip()

    def framework_definition_model_name(self) -> str:
        return (self.framework_definition_model or self.primary_model_name()).strip()

    def framework_proficiency_model_name(self) -> str:
        return (self.framework_proficiency_model or self.primary_model_name()).strip()

    @property
    def mongo_database(self) -> str:
        """Database name for the configured region."""
        return self.mongo_dev_db_name if self.mongo_region == "DEV" else self.mongo_db_name

    def mongo_uri(self) -> str | None:
        """Connection URI for the configured region, or None if it is not configured."""
        if self.mongo_region == "DEV":
            return self.mongo_dev_uri
        if not (self.mongo_username and self.mongo_password):
            return None
        host, app_name = (
            (self.mongo_uae_host, "cb-common-prod")
            if self.mongo_region == "UAE"
            else (self.mongo_ksa_host, "cb-common-prod-ksa-1")
        )
        return (
            f"mongodb+srv://{self.mongo_username}:{self.mongo_password}@{host}"
            f"/?retryWrites=true&w=majority&appName={app_name}"
        )

    def apply_runtime_env(self) -> None:
        if self.openai_api_key:
            os.environ.setdefault("OPENAI_API_KEY", self.openai_api_key)
        if self.anthropic_api_key:
            os.environ.setdefault("ANTHROPIC_API_KEY", self.anthropic_api_key)
        if self.langfuse_secret_key:
            os.environ.setdefault("LANGFUSE_SECRET_KEY", self.langfuse_secret_key)
        if self.langfuse_public_key:
            os.environ.setdefault("LANGFUSE_PUBLIC_KEY", self.langfuse_public_key)
        if self.langfuse_host:
            os.environ.setdefault("LANGFUSE_HOST", self.langfuse_host)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.apply_runtime_env()
    return settings
