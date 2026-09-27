"""Project lifecycle service."""
from sqlalchemy.orm import Session
from app.models.project import Project
from app.schemas.project import ProjectCreate

def create_project(db: Session, data: ProjectCreate) -> Project:
    """Create and persist a project."""
    obj = Project(**data.model_dump())
    db.add(obj)
    db.flush()
    return obj
