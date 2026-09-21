from typing import Annotated, Any

from fastapi import Depends

import logging

from bson import ObjectId
from bson.errors import InvalidId
from pydantic import BaseModel, Field, ValidationError

from core.edge_errors import (
    EdgeHandledError,
    FeedbackAlreadyGeneratedError,
    FeedbackGenerationInProgressError,
    ScoreNotFoundError,
    ScoreDataError,
)
from core.settings import Settings, get_settings
from domain.narrative_rules import level_from_score
from repositories.mongo_repository import InvalidIdError, MongoRepository, get_mongo_repository
from schemas.schemas import AssessmentCompetencyInput, AssessmentInput, EmployeeAssessmentsRequest

logger = logging.getLogger(__name__)


def _oid_str(value: Any) -> str | None:
    """Accept either a raw ObjectId/str or the extended-JSON {'$oid': ...} shape."""
    if isinstance(value, dict):
        return value.get("$oid")
    return str(value) if value is not None else None


class CompetencyScoreItem(BaseModel):
    competency_id: str | None = Field(default=None, alias="competencyId")
    competency_name: str = Field(alias="competencyName")
    competency_quantitative_value: float = Field(alias="competencyQuantitativeValue")

    model_config = {"populate_by_name": True}

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "CompetencyScoreItem":
        raw = dict(raw)
        raw["competencyId"] = _oid_str(raw.get("competencyId"))
        return cls.model_validate(raw)


class ScoreDocument(BaseModel):
    id: str = Field(alias="_id")
    user_id: str | None = Field(default=None, alias="scoreUserId")
    project_id: str | None = Field(default=None, alias="scoreProjectId")
    assessment_name: str = Field(alias="scoreAsessmentName")
    competencies: list[CompetencyScoreItem] = Field(default_factory=list, alias="scoreCompetenciesScores")
    feedback_generation_status: str | None = Field(default=None, alias="feedbackGenerationStatus")

    model_config = {"populate_by_name": True}

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "ScoreDocument":
        raw = dict(raw)
        for key in ("_id", "scoreUserId", "scoreProjectId"):
            raw[key] = _oid_str(raw.get(key))
        raw["scoreCompetenciesScores"] = [
            CompetencyScoreItem.from_raw(c) for c in raw.get("scoreCompetenciesScores", [])
        ]
        return cls.model_validate(raw)


class ProjectDocument(BaseModel):
    id: str = Field(alias="_id")
    project_name: str | None = Field(default=None, alias="projectName")
    company_name: str | None = Field(default=None, alias="projectCompanyName")

    model_config = {"populate_by_name": True}

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "ProjectDocument":
        raw = dict(raw)
        raw["_id"] = _oid_str(raw.get("_id"))
        return cls.model_validate(raw)


class ScoreRetrievalService:
    """score_id -> EmployeeAssessmentsRequest. Competency descriptions are DB-only here
    (from the `competencies` collection); a miss/error just leaves description unset, so the
    existing artifact-lookup / LLM-generation path in the workflow is used instead."""

    def __init__(self, repository: MongoRepository) -> None:
        self._mongo = repository
    def _fetch_score(self, project_id: str, assessment_id: str, user_id: str) -> ScoreDocument:
        raw: dict[str, Any] | None = None
        if not raw:
            try:
                raw = self._mongo.find_by_attributes(
                    "scores",
                    {
                        "scoreProjectId": ObjectId(project_id),
                        "scoreAssessmentId": ObjectId(assessment_id),
                        "scoreUserId": ObjectId(user_id),
                    },
                )
            except (InvalidIdError, InvalidId, TypeError) as exc:
                logger.warning("Invalid ID when looking for score: project_id=%s, assessment_id=%s, user_id=%s: %s", project_id, assessment_id, user_id, exc)
                logger.info("Score not found for : project_id=%s, assessment_id=%s, user_id=%s", project_id, assessment_id, user_id)
                raise ScoreNotFoundError()
            if not raw:
                logger.info("Score not found: project_id=%s, assessment_id=%s, user_id=%s", project_id, assessment_id, user_id)
                raise ScoreNotFoundError()
        if not isinstance(raw, dict):
            raise ScoreDataError(f"This Score is not a valid document: {type(raw).__name__}")
        try:
            score = ScoreDocument.from_raw(raw)
        except ValidationError as exc:
            logger.warning("Malformed score document %s: %s", f"project_id={project_id}, assessment_id={assessment_id}, user_id={user_id}", exc)
            raise ScoreDataError(f"This Score is malformed: {exc}") from exc
        if not score.competencies:
            logger.warning("Score project_id=%s, assessment_id=%s, user_id=%s has no competency scores", project_id, assessment_id, user_id)
            raise ScoreDataError(f"This Score has no competency scores.")
        return score

    def _fetch_project(self, project_id: str | None) -> ProjectDocument | None:
        if not project_id:
            return None
        try:
            raw = self._mongo.find_by_id("projects", project_id)
        except Exception as exc:
            logger.warning("Project lookup failed for %s, continuing without project: %s", project_id, exc)
            return None
        if not raw:
            logger.info("Project not found: %s", project_id)
            return None
        try:
            return ProjectDocument.from_raw(raw)
        except ValidationError as exc:
            # project is optional context only; a malformed doc shouldn't fail the run
            logger.warning("Malformed project document %s, continuing without project: %s", project_id, exc)
            return None

    def _fetch_competency_description(self, competency_id: str | None) -> str | None:
        if not competency_id:
            return None
        try:
            raw = self._mongo.find_by_id("competencies", competency_id)
        except Exception as exc:
            logger.info("Competency lookup failed for %s, falling back to LLM/artifact path: %s", competency_id, exc)
            return None
        desc = (raw or {}).get("competencyDescription")
        if not (isinstance(desc, str) and desc.strip()):
            logger.debug("No DB description for competency %s, falling back to LLM/artifact path", competency_id)
            return None
        return desc.strip()

    def build_employee_assessments_request(self, project_id: str, assessment_id: str, user_id: str, force_rerun: bool = False) -> EmployeeAssessmentsRequest:
        logger.info("Building employee assessments request from project_id=%s, assessment_id=%s, user_id=%s", project_id, assessment_id, user_id)
        score = self._fetch_score(project_id, assessment_id, user_id)
        project = self._fetch_project(project_id)
        status = (score.feedback_generation_status or "").strip().lower()
        if status == "completed" and not force_rerun:
            logger.info("Feedback already generated for score %s", score.id)
            raise FeedbackAlreadyGeneratedError()
        if status == "in progress":
            logger.info("Feedback generation in progress for score %s", score.id)
            raise FeedbackGenerationInProgressError()
        
        competencies: list[AssessmentCompetencyInput] = []
        for comp in score.competencies:
            score_percent = float(comp.competency_quantitative_value)
            description = self._fetch_competency_description(comp.competency_id)
            competencies.append(
                AssessmentCompetencyInput(
                    competency=comp.competency_name,
                    score_percent=score_percent,
                    achieved_level=level_from_score(score_percent),
                    benchmark_level=None,  # no benchmark on a score document
                    gap_percent=None,
                    description=description,
                )
            )

        assessment = AssessmentInput(assessment_name=score.assessment_name, competencies=competencies)
        return EmployeeAssessmentsRequest(
            user_id=score.user_id or score.id,
            organization=project.company_name if project else None,
            project_id=project_id,
            assessment_id=assessment_id,
            role=None,  # not present on the score/project payloads
            industry=None,
            seniority=None,
            assessment=assessment,
        )


def get_score_retrieval_service(
    repository: Annotated[MongoRepository, Depends(get_mongo_repository)],
) -> ScoreRetrievalService:
    return ScoreRetrievalService(repository=repository)
