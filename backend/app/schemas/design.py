"""Design state schemas."""
import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
from app.schemas.common import ORMModel

class DesignStateInput(BaseModel):
    pages: list[dict[str, Any]] = Field(default_factory=list)
    components: list[dict[str, Any]] = Field(default_factory=list)
    design_tokens: dict[str, Any] = Field(default_factory=dict)
    ux_navigation: dict[str, Any] = Field(default_factory=dict)
    assets: list[dict[str, Any]] = Field(default_factory=list)
    design_laws: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    direction_selection: dict[str, Any] = Field(default_factory=dict)

class DesignStateRead(ORMModel):
    project_id: uuid.UUID
    state: dict[str, Any]
    current_version_id: uuid.UUID | None
    updated_at: datetime

class DesignStateUpdate(BaseModel):
    state: DesignStateInput
    change_summary: str = Field(min_length=1, max_length=2000)

class SurgicalEdit(BaseModel):
    """Path-based future-ready patch request. Paths use dot-separated object keys and numeric list indices."""
    path: str = Field(min_length=1, max_length=500)
    value: Any
    change_summary: str = Field(min_length=1, max_length=2000)
