"""Memory persistence and retrieval."""
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.memory import DesignMemory
from app.models.project import Project
from app.schemas.memory import MemoryCreate

def store_memory(db: Session, project_id: uuid.UUID, data: MemoryCreate) -> DesignMemory:
    """Store provenance-classified memory for a valid project."""
    if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
    obj = DesignMemory(project_id=project_id, **data.model_dump())
    db.add(obj); db.flush(); return obj

def get_project_memory(db: Session, project_id: uuid.UUID) -> list[DesignMemory]:
    """Return all memory entries for a project, including their trust status."""
    if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
    return list(db.scalars(select(DesignMemory).where(DesignMemory.project_id == project_id).order_by(DesignMemory.created_at)))
