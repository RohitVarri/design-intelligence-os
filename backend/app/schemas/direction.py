"""Design direction and independent assessment schemas."""
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.models.direction import DirectionStatus
from app.models.direction_assessment import AssessmentCriterion

class DirectionCreate(BaseModel):
    generate: bool = False
    name: str | None = None
    description: str | None = None
    visual_language: dict = Field(default_factory=dict)
    typography_direction: str | None = None
    color_direction: str | None = None
    layout_direction: str | None = None
    navigation_direction: str | None = None
    imagery_direction: str | None = None
    motion_direction: str | None = None
    component_direction: str | None = None
    density: str | None = None
    emotional_tone: list[str] = Field(default_factory=list)
    target_audience_fit: str | None = None
    strengths: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    supporting_research_ids: list[uuid.UUID] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def require_name_when_manual(self):
        if not self.generate and not self.name:
            raise ValueError("name is required unless generate=true")
        return self

class DirectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    intent_id: uuid.UUID
    name: str
    description: str
    visual_language: dict
    typography_direction: str | None
    color_direction: str | None
    layout_direction: str | None
    navigation_direction: str | None
    imagery_direction: str | None
    motion_direction: str | None
    component_direction: str | None
    density: str | None
    emotional_tone: list[str]
    target_audience_fit: str | None
    strengths: list[str]
    tradeoffs: list[str]
    risks: list[str]
    supporting_research_ids: list[str]
    confidence: float
    provenance: dict
    status: DirectionStatus
    created_at: datetime

class DirectionAssessmentCreate(BaseModel):
    criterion: AssessmentCriterion
    observation: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    tradeoff: str = Field(min_length=1)

class DirectionAssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    direction_id: uuid.UUID
    criterion: AssessmentCriterion
    observation: str
    evidence: str
    confidence: float
    tradeoff: str
    created_at: datetime

class DirectionStatusUpdate(BaseModel):
    status: DirectionStatus

    @model_validator(mode="after")
    def cannot_select_through_update(self):
        if self.status == DirectionStatus.SELECTED:
            raise ValueError("Use the explicit selection endpoint to select a direction")
        return self

class DirectionSelection(BaseModel):
    confirm: bool

    @model_validator(mode="after")
    def require_explicit_confirmation(self):
        if not self.confirm:
            raise ValueError("Explicit user confirmation is required")
        return self
