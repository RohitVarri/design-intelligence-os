"""Research evidence and plan schemas."""
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.models.research_evidence import EvidenceSourceType, EvidenceTrust, TrendStage
from app.models.research_plan import ResearchPlanStatus
from app.models.research_query import ResearchQueryPriority, ResearchQueryStatus

class ResearchEvidenceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    claim: str = Field(min_length=1)
    source_url: str | None = None
    source_name: str | None = None
    source_type: EvidenceSourceType = EvidenceSourceType.OTHER
    published_at: datetime | None = None
    industry: str | None = None
    audience: str | None = None
    evidence: str = Field(min_length=1)
    relevance: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    trend_stage: TrendStage = TrendStage.UNKNOWN
    tags: list[str] = Field(default_factory=list)
    related_requirement: str | None = None
    trust: EvidenceTrust = EvidenceTrust.UNTRUSTED

class ResearchEvidenceRead(ResearchEvidenceCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    intent_id: uuid.UUID | None
    retrieved_at: datetime
    created_at: datetime
    provenance: dict

class ResearchQueryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    plan_id: uuid.UUID
    query: str
    research_area: str
    reason: str
    priority: ResearchQueryPriority
    status: ResearchQueryStatus
    created_at: datetime

class ResearchPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    intent_id: uuid.UUID
    status: ResearchPlanStatus
    created_at: datetime
    updated_at: datetime
    queries: list[ResearchQueryRead] = Field(default_factory=list)
