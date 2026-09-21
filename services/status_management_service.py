import asyncio
import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import Depends

from bson import ObjectId

from schemas.schemas import RunEnvelope

from repositories.mongo_repository import MongoRepository, get_mongo_repository

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _score_query(project_id: str, assessment_id: str, user_id: str) -> dict[str, Any]:
    return {
        "scoreProjectId": ObjectId(project_id),
        "scoreAssessmentId": ObjectId(assessment_id),
        "scoreUserId": ObjectId(user_id),
    }


class StatusManagementService:

    """Statuses are keyed by score_id, which doubles as the natural dedup key."""

    def __init__(
        self,
        repository: MongoRepository | None = None,
    ) -> None:
        self._storage = repository
     
  
    async def set_in_progress(self, request_data: dict[str, Any]) -> RunEnvelope:
        """Unconditionally start a fresh run (force_rerun path), replacing any existing one."""
        project_id = request_data.get("project_id")
        assessment_id = request_data.get("assessment_id")
        user_id = request_data.get("user_id")
        self._storage.update_by_attributes(
            "scores",
            _score_query(project_id, assessment_id, user_id),
            {"feedbackGenerationStatus": "in progress"}, 
        )
        return RunEnvelope(
            project_id=project_id,
            assessment_id=assessment_id,
            user_id=user_id,
            status="in progress",
            created_at=_utc_now_iso(),
            updated_at=_utc_now_iso(),
        )


    async def set_completed(self, result: dict[str, Any]) -> dict[str, Any] | None:
        query = _score_query(result.get("project_id"), result.get("assessment_id"), result.get("user_id"))
        try:
            self._storage.update_by_attributes(
                "scores",
                query,
                {"feedbackGenerationStatus": "completed", "ExecutiveSummary": result.get("payload", {}).get("executive_summary")},
            )
            for comp in result.get("payload", {}).get("scores_feedback", []):
                self._storage.update_by_attributes(
                    "scores",
                    query,
                    {
                        "scoreCompetenciesScores.$[elem].competencyInterpretation": comp.get("interpretation"),
                    },
                    array_filters=[{"elem.competencyName": comp.get("name")}],
                )
        except Exception as exc:
            logger.error("Failed to set run as completed: %s", exc)
            await self.set_failed(result, str(exc))

    async def set_failed(self, result: dict[str, Any], error: str) -> dict[str, Any] | None:
        query = _score_query(result.get("project_id"), result.get("assessment_id"), result.get("user_id"))
        try:
            self._storage.update_by_attributes(
                "scores",
                query,
                {"feedbackGenerationStatus": "failed", "error": error},
            )
        except Exception as exc:
            logger.error("Failed to set run as failed: %s", exc)


def get_status_manager(
    repository: Annotated[MongoRepository, Depends(get_mongo_repository)],
) -> StatusManagementService:
    return StatusManagementService(repository=repository)
