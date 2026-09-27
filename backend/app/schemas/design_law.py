"""Design law schemas."""
import uuid
from datetime import datetime
from app.schemas.common import ORMModel
from pydantic import BaseModel, Field

class DesignLawCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    rule: str = Field(min_length=1)

class DesignLawUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    rule: str | None = Field(default=None, min_length=1)
    active: bool | None = None

class DesignLawRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    rule: str
    active: bool
    created_at: datetime
    updated_at: datetime
