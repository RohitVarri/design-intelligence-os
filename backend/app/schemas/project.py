"""Project schemas."""
import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from app.schemas.common import ORMModel

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)

class ProjectRead(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
