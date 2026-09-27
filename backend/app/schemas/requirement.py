"""Design requirement schemas preserve source distinctions."""
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.models.requirement import RequirementCategory, RequirementSource, RequirementStatus

class RequirementCreate(BaseModel):
    requirement: str = Field(min_length=1)
    category: RequirementCategory
    priority: str = "medium"
    source: RequirementSource
    rationale: str = Field(min_length=1)
    status: RequirementStatus = RequirementStatus.PROPOSED
    confidence: float = Field(default=0, ge=0, le=1)
    evidence_id: uuid.UUID | None = None

class RequirementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    intent_id: uuid.UUID | None
    requirement: str
    category: RequirementCategory
    priority: str
    source: RequirementSource
    rationale: str
    status: RequirementStatus
    confidence: float
    provenance: dict
    created_at: datetime
