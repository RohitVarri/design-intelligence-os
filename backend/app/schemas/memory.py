"""Design memory schemas."""
import uuid
from datetime import datetime
from app.models.memory import MemoryTrust
from app.schemas.common import ORMModel
from pydantic import BaseModel, Field

class MemoryCreate(BaseModel):
    category: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1)
    trust: MemoryTrust

class MemoryRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    category: str
    content: str
    trust: MemoryTrust
    created_at: datetime
