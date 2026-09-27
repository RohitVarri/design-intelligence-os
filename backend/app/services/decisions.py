"""Design decision recording."""
import uuid
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models.decision import DesignDecision
from app.models.project import Project
from app.schemas.decision import DecisionCreate

def record_decision(db: Session, project_id: uuid.UUID, data: DecisionCreate) -> DesignDecision:
    """Record a decision and preserve its declared origin."""
    if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
    decision = DesignDecision(project_id=project_id, **data.model_dump())
    db.add(decision); db.flush(); return decision
