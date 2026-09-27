"""User-owned design-law operations."""
import uuid
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.design_law import DesignLaw
from app.models.design_state import DesignState
from app.models.project import Project
from app.schemas.design_law import DesignLawCreate, DesignLawUpdate
from app.services.design_state import create_initial_design_state, update_design_state

def _version_laws(db: Session, project_id: uuid.UUID, summary: str) -> None:
    """Mirror law records into design state and snapshot the resulting state."""
    state = db.get(DesignState, project_id)
    if state is None:
        state = create_initial_design_state(db, project_id)
    laws = db.scalars(select(DesignLaw).where(DesignLaw.project_id == project_id).order_by(DesignLaw.created_at)).all()
    next_state = dict(state.state)
    next_state["design_laws"] = [
        {"id": str(law.id), "title": law.title, "rule": law.rule, "active": law.active} for law in laws
    ]
    update_design_state(db, project_id, next_state, summary)

def create_design_law(db: Session, project_id: uuid.UUID, data: DesignLawCreate) -> DesignLaw:
    """Create a law only for an existing project."""
    if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
    law = DesignLaw(project_id=project_id, **data.model_dump())
    db.add(law); db.flush()
    _version_laws(db, project_id, f"Added design law: {law.title}")
    return law

def update_design_law(db: Session, project_id: uuid.UUID, law_id: uuid.UUID, data: DesignLawUpdate) -> DesignLaw:
    """Update law attributes without changing unrelated design state."""
    law = db.scalar(select(DesignLaw).where(DesignLaw.id == law_id, DesignLaw.project_id == project_id))
    if not law: raise HTTPException(404, "Design law not found")
    for key, value in data.model_dump(exclude_unset=True).items(): setattr(law, key, value)
    db.flush()
    _version_laws(db, project_id, f"Updated design law: {law.title}")
    return law
