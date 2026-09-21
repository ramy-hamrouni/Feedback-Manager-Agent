import asyncio
import logging
import uuid
from datetime import datetime, timezone
from time import perf_counter
from typing import Annotated, Any

from fastapi import Depends

from core.logging_config import run_id_var
from core.settings import Settings, get_settings
from schemas.schemas import (
    AssessmentResultsPayload,
    EmployeeAssessmentsRequest,
    RunEnvelope,

    ScoreFeedback,
)
from services.narrative_llm_service import NarrativeLLMService, get_narrative_llm_service
from services.score_document_builder_service import ScoreDocumentBuilder, get_score_document_builder
from services.narrative_artifacts_service import NarrativeArtifactsService, get_artifacts_service
from services.status_management_service import StatusManagementService, get_status_manager
from workflows.narrative_feedback_workflow import NarrativeFeedbackWorkflow

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _result_url(score_id: str) -> str:
    return f"/api/v1/scores/{score_id}/result"


class NarrativeFeedbackService:
    def __init__(
        self,
        status_manager: StatusManagementService,
        llm_service: NarrativeLLMService,
        settings: Settings,
        document_builder: ScoreDocumentBuilder,
        artifacts: NarrativeArtifactsService | None = None,
    ) -> None:
        self._status_manager = status_manager
        self._settings = settings
        self._document_builder = document_builder
        self._workflow = NarrativeFeedbackWorkflow(settings, llm_service, artifacts)
        self._artifacts = artifacts

    def to_run_envelope(self, score_id: str, run: dict[str, Any], reused: bool) -> RunEnvelope:
        return RunEnvelope(
            score_id=score_id,
            status=run["status"],
            reused=reused,
            result_url=_result_url(score_id),
            created_at=run["created_at"],
            updated_at=run["updated_at"],
        )

    async def create_run(
        self, req: EmployeeAssessmentsRequest
    ) -> RunEnvelope:
        request_data = req.model_dump()
        run_id = uuid.uuid4().hex[:8]
        logger.info(
            "Run %s accepted: project_id=%s assessment_id=%s user_id=%s score_id=%s",
            run_id,
            request_data.get("project_id"),
            request_data.get("assessment_id"),
            request_data.get("user_id"),
            request_data.get("score_id"),
        )
        envelope = await self._status_manager.set_in_progress(request_data=request_data)
        logger.info("Run %s marked in progress; starting pipeline in background", run_id)
        asyncio.create_task(self._process_run(req, run_id))
        return envelope


    async def _process_run(self, req: EmployeeAssessmentsRequest, run_id: str = "-") -> None:
        run_id_var.set(run_id)
        started = perf_counter()
        request_data = req.model_dump()
        result: dict[str, Any] = {
            "user_id": request_data.get("user_id"),
            "project_id": request_data.get("project_id"),
            "assessment_id": request_data.get("assessment_id"),
            "score_id": request_data.get("score_id"),
        }
        score_id = request_data.get("score_id")
        try:
            assessment = request_data["assessment"]
            competencies = self._document_builder.build_competencies(assessment)
            logger.info(
                "Input normalized: assessment=%r competencies=%d (scored 0%%: %d, benchmarked: %d)",
                assessment.get("assessment_name"),
                len(competencies),
                sum(1 for c in competencies if float(c["score_percent"]) == 0),
                sum(1 for c in competencies if c.get("benchmark_level")),
            )

            final_state = await self._workflow.run_assessment(
                request_data=request_data,
                assessment=assessment,
                competencies=competencies,
            )

            pipeline_trace = list(final_state.get("pipeline_trace") or [])
            step_sources = dict(final_state.get("step_sources") or {})
            if any(step_sources.values()):
                pipeline_trace.append(
                    {
                        "step": "web_search_sources",
                        "sources": {k: sorted(set(v)) for k, v in step_sources.items() if v},
                    }
                )

            feedback_competencies = list(final_state.get("feedback_competencies") or [])
            executive_summary = str(final_state.get("executive_summary") or "")

            scores_feedback = [
                ScoreFeedback(
                    name=comp["name"],
                    achieved_level=comp.get("achieved_level", ""),
                    interpretation=comp.get("interpretation", ""),
                )
                for comp in feedback_competencies
            ]

            if not scores_feedback:
                raise ValueError("Assessment produced no competency feedback.")

            ready_payload = AssessmentResultsPayload(
                executive_summary=executive_summary,
                scores_feedback=scores_feedback,
            )

            result = {
                **result,
                "status": "completed",
                "payload": ready_payload.model_dump(by_alias=True),
                "meta": {
                    "pipeline_version": "v7-inspired",
                    "parameters": self._workflow.pipeline_parameters(),
                    "steps": pipeline_trace,
                    "framework_rows_loaded": self._artifacts.framework_rows_loaded,
                    "competency_descriptions_loaded": self._artifacts.competency_descriptions_loaded,
                    "artifact_source": self._artifacts.artifact_info,
                    "generated_at": _utc_now_iso(),
                },
            }
            logger.info("Persisting completed result for score_id=%s", score_id)
            await self._status_manager.set_completed(result)
            logger.info(
                "Run finished in %.1fs: %d competency score(s), executive summary %d chars",
                perf_counter() - started,
                len(scores_feedback),
                len(executive_summary or ""),
            )
        except Exception as exc:
            logger.exception(
                "Run FAILED after %.1fs (score_id=%s): %s",
                perf_counter() - started,
                score_id,
                exc,
            )
            await self._status_manager.set_failed(result, str(exc))


def get_feedback_service(
    status_manager: Annotated[StatusManagementService, Depends(get_status_manager)],
    llm_service: Annotated[NarrativeLLMService, Depends(get_narrative_llm_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    document_builder: Annotated[ScoreDocumentBuilder, Depends(get_score_document_builder)],
    artifacts: Annotated[NarrativeArtifactsService, Depends(get_artifacts_service)],
) -> NarrativeFeedbackService:
    return NarrativeFeedbackService(
        status_manager=status_manager,
        llm_service=llm_service,
        settings=settings,
        document_builder=document_builder,
        artifacts=artifacts,
    )
