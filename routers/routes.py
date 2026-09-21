from typing import Annotated

import asyncio

from fastapi import APIRouter, Depends, Response, status,BackgroundTasks

from schemas.schemas import RunEnvelope, ScoreRunRequest
from services.narrative_feedback_service import NarrativeFeedbackService, get_feedback_service
from services.score_retrieval_service import get_score_retrieval_service,ScoreRetrievalService


router = APIRouter(tags=["runs"])

@router.post(
    "/scores/run",
    response_model=RunEnvelope,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_run(
    req: ScoreRunRequest,
    background_tasks: BackgroundTasks,
    score_service: Annotated[
        ScoreRetrievalService,
        Depends(get_score_retrieval_service),
    ],
    feedback_service: Annotated[
        NarrativeFeedbackService,
        Depends(get_feedback_service),
    ],
) -> RunEnvelope:

    assessments_req = await asyncio.to_thread(
        score_service.build_employee_assessments_request,
        req.project_id,
        req.assessment_id,
        req.user_id,
        force_rerun=req.force_rerun,
    )

    background_tasks.add_task(
        feedback_service.create_run,
        assessments_req,
    )

    return RunEnvelope(status="accepted")


