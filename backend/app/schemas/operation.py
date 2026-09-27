"""Proposed design operation schemas; no state mutation endpoint exists."""
import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.models.operation import OperationActor, OperationSource, OperationStatus, OperationType

class OperationCreate(BaseModel):
    operation_type: OperationType
    actor: OperationActor
    target: str = Field(min_length=1, max_length=500)
    property: str | None = None
    old_value: Any = None
    new_value: Any = None
    scope: str = "project"
    reason: str = Field(min_length=1)
    source: OperationSource
    status: OperationStatus = OperationStatus.PROPOSED
    parent_operation_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def proposals_only(self):
        if self.status != OperationStatus.PROPOSED:
            raise ValueError("Operations must be proposed; lifecycle transitions require dedicated validation and approval services")
        if self.actor == OperationActor.AI and self.source != OperationSource.AI_PROPOSAL:
            raise ValueError("AI operations must retain ai_proposal source provenance")
        return self

class OperationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    operation_type: OperationType
    actor: OperationActor
    target: str
    property: str | None
    old_value: Any
    new_value: Any
    scope: str
    reason: str
    source: OperationSource
    status: OperationStatus
    parent_operation_id: uuid.UUID | None
    created_at: datetime
