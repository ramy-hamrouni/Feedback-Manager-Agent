import asyncio
import logging
from collections import Counter
import uuid
from datetime import datetime, timezone
from time import perf_counter
from typing import Annotated, Any

from fastapi import Depends

from core.logging_config import run_id_var
from core.tracing import (
    emit_run_telemetry,
    flush as flush_tracing,
    observe,
    propagate_attributes,
    reset_run_telemetry,
    run_tokens,
    tokens_by_node,
    usage_by_model,
)
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


    @staticmethod
    def _trace_metadata(
        request_data: dict[str, Any],
        final_state: dict[str, Any] | None,
        run_ms: float,
        status: str,
    ) -> dict[str, Any]:
        """Everything worth filtering a trace on — including the two provenance maps
        (description_sources / levels_sources) that otherwise never leave the graph."""
        state = final_state or {}
        trace = list(state.get("pipeline_trace") or [])
        description_sources = dict(state.get("description_sources") or {})
        levels_sources = dict(state.get("levels_sources") or {})
        toks = run_tokens()
        return {
            "status": status,
            "pipeline_version": "v7-inspired",
            "run_latency_ms": run_ms,
            "user_id": request_data.get("user_id"),
            "project_id": request_data.get("project_id"),
            "assessment_id": request_data.get("assessment_id"),
            "organization": request_data.get("organization"),
            "assessment": (request_data.get("assessment") or {}).get("assessment_name"),
            "competency_count": len(state.get("competencies") or []),
            "resolved_role": state.get("resolved_role"),
            "nodes": [f"{i + 1}. {s.get('step')} — {s.get('duration_ms')}ms" for i, s in enumerate(trace)],
            "node_count": len(trace),
            "node_ms": {s.get("step"): s.get("duration_ms") for s in trace},
            "llm_calls": toks["calls"],
            "tokens_input": toks["input"],
            "tokens_output": toks["output"],
            "tokens_total": toks["total"],
            "tokens_by_node": tokens_by_node(),
            "models": {
                m: {"calls": u["calls"], "input": u["input"], "output": u["output"]}
                for m, u in usage_by_model().items()
            },
            "description_sources": description_sources,
            "description_source_counts": dict(Counter(description_sources.values())),
            "levels_sources": levels_sources,
            "levels_source_counts": dict(Counter(levels_sources.values())),
            "web_search_sources": {k: sorted(set(v)) for k, v in (state.get("step_sources") or {}).items() if v},
            "parse_ok": state.get("parse_ok"),
            "groundedness_score": state.get("groundedness_score"),
            "groundedness_passed": state.get("groundedness_passed"),
            "competency_sections": len(state.get("feedback_competencies") or []),
            "executive_summary_chars": len(str(state.get("executive_summary") or "")),
        }

    @observe(name="feedback_agent_assessment")
    async def _process_run(self, req: EmployeeAssessmentsRequest, run_id: str = "-") -> None:
        run_id_var.set(run_id)
        reset_run_telemetry()
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
                "Input normalized: assessment=%r competencies=%d (scored 0%%: %d)",
                assessment.get("assessment_name"),
                len(competencies),
                sum(1 for c in competencies if float(c["score_percent"]) == 0),
            )

            with propagate_attributes(
                trace_name=f"feedback_agent · {assessment.get('assessment_name') or 'assessment'}",
                session_id=str(request_data.get("user_id") or run_id),
                tags=["feedback_agent", "narrative", "v7-inspired"],
            ):
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
            run_ms = round((perf_counter() - started) * 1000, 1)
            logger.info(
                "Run finished in %.1fs: %d competency score(s), executive summary %d chars",
                perf_counter() - started,
                len(scores_feedback),
                len(executive_summary or ""),
            )
            emit_run_telemetry(
                self._trace_metadata(request_data, final_state, run_ms, "completed"),
                scores={
                    "latency_ms": (run_ms, f"{len(pipeline_trace)} nodes"),
                    "tokens_total": (run_tokens()["total"], f"{run_tokens()['calls']} llm calls"),
                    "groundedness": (
                        final_state.get("groundedness_score"),
                        f"parse_ok={final_state.get('parse_ok')}",
                    ),
                },
            )
            flush_tracing()
        except Exception as exc:
            logger.exception(
                "Run FAILED after %.1fs (score_id=%s): %s",
                perf_counter() - started,
                score_id,
                exc,
            )
            emit_run_telemetry(
                self._trace_metadata(
                    request_data, None, round((perf_counter() - started) * 1000, 1), "failed"
                ),
                scores={"latency_ms": round((perf_counter() - started) * 1000, 1)},
            )
            flush_tracing()
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
