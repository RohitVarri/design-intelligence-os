"""Decision schemas."""
import uuid
from datetime import datetime
from app.models.decision import DecisionSource
from app.schemas.common import ORMModel
from pydantic import BaseModel, Field

class DecisionCreate(BaseModel):
    source: DecisionSource
    title: str = Field(min_length=1, max_length=300)
    rationale: str = Field(min_length=1)
    provenance: dict = Field(default_factory=dict)

class DecisionRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    source: DecisionSource
    title: str
    rationale: str
    provenance: dict
    created_at: datetime
