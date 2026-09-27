"""Schemas for deterministic intent extraction and editing."""
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.models.intent import IntentStatus

class IntentCreate(BaseModel):
    raw_request: str = Field(min_length=1)

class IntentUpdate(BaseModel):
    raw_request: str | None = Field(default=None, min_length=1)
    project_type: str | None = None
    business_or_product_goal: str | None = None
    primary_audience: str | None = None
    secondary_audience: str | None = None
    primary_user_tasks: list[str] | None = None
    desired_user_action: str | None = None
    industry: str | None = None
    platform: str | None = None
    target_devices: list[str] | None = None
    required_pages: list[str] | None = None
    required_features: list[str] | None = None
    content_requirements: list[str] | None = None
    brand_requirements: list[str] | None = None
    visual_preferences: list[str] | None = None
    functional_requirements: list[str] | None = None
    technical_requirements: list[str] | None = None
    accessibility_requirements: list[str] | None = None
    performance_requirements: list[str] | None = None
    constraints: list[str] | None = None
    references: list[str] | None = None
    competitors: list[str] | None = None
    success_criteria: list[str] | None = None
    budget_or_resource_constraints: str | None = None
    timeline_constraints: str | None = None

class IntentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    revision_number: int = 1
    created_by: str = "user"
    superseded_by_id: uuid.UUID | None = None
    raw_request: str
    project_type: str | None
    business_or_product_goal: str | None
    primary_audience: str | None
    secondary_audience: str | None
    primary_user_tasks: list[str]
    desired_user_action: str | None
    industry: str | None
    platform: str | None
    target_devices: list[str]
    required_pages: list[str]
    required_features: list[str]
    content_requirements: list[str]
    brand_requirements: list[str]
    visual_preferences: list[str]
    functional_requirements: list[str]
    technical_requirements: list[str]
    accessibility_requirements: list[str]
    performance_requirements: list[str]
    constraints: list[str]
    references: list[str]
    competitors: list[str]
    success_criteria: list[str]
    budget_or_resource_constraints: str | None
    timeline_constraints: str | None
    confidence: float
    completeness: float
    provenance: dict
    status: IntentStatus
    created_at: datetime
    updated_at: datetime

class IntentAnalysisRead(BaseModel):
    intent: IntentRead
    missing_information: list[str]
    generated_questions: int
