"""Strict structured contracts for proposed wireframe sets."""
import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictWireframeModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class WireframeRegion(StrictWireframeModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    hierarchy_order: int = Field(ge=1)
    content_elements: list[str]
    component_refs: list[str]
    interactions: list[str]


class WireframePage(StrictWireframeModel):
    page_id: str = Field(min_length=1)
    layout_summary: str = Field(min_length=1)
    regions: list[WireframeRegion] = Field(min_length=1)
    responsive_notes: list[str]
    accessibility_notes: list[str]
    rationale: str = Field(min_length=1)


class WireframeOutput(StrictWireframeModel):
    pages: list[WireframePage] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class WireframeSetStatus(str, Enum):
    PROPOSED = "proposed"
    PREVIEWED = "previewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class WireframeCandidateResponse(StrictWireframeModel):
    run_id: uuid.UUID
    candidate_id: uuid.UUID | None
    status: str
    candidate: WireframeOutput | dict[str, Any] | None
    accepted: bool


class WireframeSetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    design_plan_id: uuid.UUID
    intent_id: uuid.UUID
    direction_id: uuid.UUID
    status: WireframeSetStatus
    wireframe: dict[str, Any]
    provenance: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None
    approved_by: str | None
