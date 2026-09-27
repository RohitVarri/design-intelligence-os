"""Version schemas."""
import uuid
from datetime import datetime
from typing import Any
from app.schemas.common import ORMModel

class VersionRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    version_number: int
    parent_version_id: uuid.UUID | None
    state: dict[str, Any]
    change_summary: str
    created_at: datetime

class VersionComparison(ORMModel):
    from_version: VersionRead
    to_version: VersionRead
    changes: dict[str, Any]
