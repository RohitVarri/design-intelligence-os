"""Strict structured output schemas returned by providers."""
from pydantic import BaseModel, ConfigDict, Field


class CandidateField(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    value: str | list[str] | None
    confidence: float = Field(ge=0, le=1)
    uncertainty: str = ""
    rationale: str = Field(min_length=1)
    source: str = "ai_proposal"


class IntentCandidateOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    fields: dict[str, CandidateField]
    summary: str = ""


class QuestionCandidateOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    question: str = Field(min_length=5)
    target_field: str
    answer_type: str
    dependencies: list[str]
    impact_score: float = Field(ge=0, le=100)
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class QuestionCandidatesOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    questions: list[QuestionCandidateOutput]


class ResearchResultCandidate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    claim: str = Field(min_length=1)
    source_name: str | None = None
    source_url: str | None = None
    citation: dict = Field(default_factory=dict)
    evidence: str = Field(min_length=1)
    related_requirement: str | None = None


class ResearchResultsOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    results: list[ResearchResultCandidate]


class DesignProposalOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    operation_type: str
    target: str = Field(min_length=1, max_length=500)
    property: str | None = None
    new_value: object
    reason: str = Field(min_length=1)
    research_ids: list[str] = Field(default_factory=list)
