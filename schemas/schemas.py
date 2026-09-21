from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field



class AssessmentCompetencyInput(BaseModel):
    competency: str = Field(min_length=1)
    score_percent: float = Field(ge=0.0, le=100.0)
    achieved_level: str = Field(default="Not specified")  # shown to the reader (stored level, e.g. "Expert")
    framework_level: str | None = None  # 3-band lookup key for level descriptions; never rendered
    description: str | None = None  # DB-provided (score-id path); falls back to the LLM/artifact path if unset


class AssessmentInput(BaseModel):
    assessment_name: str = Field(min_length=1)
    competencies: list[AssessmentCompetencyInput] = Field(min_length=1)


class EmployeeAssessmentsRequest(BaseModel):
    user_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    assessment_id: str = Field(min_length=1)
    organization: str | None = None
    role: str | None = None
    industry: str | None = None
    seniority: str | None = None
    assessment: AssessmentInput


class ScoreRunRequest(BaseModel):
    force_rerun: bool = False
    project_id: str 
    assessment_id:str
    user_id: str


class RunEnvelope(BaseModel):
    project_id: str
    user_id: str
    assessment_id: str
    status: str
    created_at: str


class CompetencyFeedback(BaseModel):
    name: str
    achieved_level: str
    score_percent: float
    interpretation: str
    definition: str = ""


class FeedbackPayload(BaseModel):
    executive_summary: str
    competencies: list[CompetencyFeedback]
    competency_narratives: str = ""
    missing_competencies: list[str] = Field(default_factory=list, alias="_missing_competencies")


class AssessmentResultItem(BaseModel):
    assessment_name: str
    competency_count: int
    parse_ok: bool
    feedback: FeedbackPayload
    groundedness_score: float | None = None
    groundedness_passed: bool | None = None




class ScoreFeedback(BaseModel):
    name: str
    achieved_level: str
    interpretation: str


class AssessmentResultsPayload(BaseModel):
    executive_summary: str
    scores_feedback: list[ScoreFeedback]


class RunResultPending(BaseModel):
    project_id: str
    assessment_id: str
    user_id: str
    status: str
    message: str
    result_url: str


class RunResultReady(BaseModel):
    project_id: str
    assessment_id: str
    user_id: str
    status: Literal["completed"]
    payload: AssessmentResultsPayload
    meta: dict[str, Any]


