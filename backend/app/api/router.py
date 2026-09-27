"""Versioned API routes for BUILD 01."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.decision import DesignDecision
from app.models.design_law import DesignLaw
from app.models.project import Project
from app.models.version import DesignVersion
from app.schemas.project import ProjectCreate, ProjectRead
from app.schemas.design import DesignStateInput, DesignStateRead, DesignStateUpdate, SurgicalEdit
from app.schemas.version import VersionRead, VersionComparison
from app.schemas.decision import DecisionCreate, DecisionRead
from app.schemas.design_law import DesignLawCreate, DesignLawUpdate, DesignLawRead
from app.schemas.memory import MemoryCreate, MemoryRead
from app.services.projects import create_project
from app.services.design_state import create_initial_design_state, get_design_state, update_design_state, surgical_edit
from app.services.versioning import get_version, compare_versions, restore_version
from app.services.memory import store_memory, get_project_memory
from app.services.decisions import record_decision
from app.services.design_laws import create_design_law, update_design_law

router = APIRouter()

def _project(db: Session, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if not project: raise HTTPException(404, "Project not found")
    return project

@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def post_project(data: ProjectCreate, db: Session = Depends(get_db)):
    project = create_project(db, data); db.commit(); db.refresh(project); return project

@router.get("/projects", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)):
    return list(db.scalars(select(Project).order_by(Project.created_at.desc())))

@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: uuid.UUID, db: Session = Depends(get_db)):
    return _project(db, project_id)

@router.post("/projects/{project_id}/design", response_model=DesignStateRead, status_code=201)
def post_design(project_id: uuid.UUID, db: Session = Depends(get_db)):
    obj = create_initial_design_state(db, project_id); db.commit(); db.refresh(obj); return obj

@router.get("/projects/{project_id}/design", response_model=DesignStateRead)
def read_design(project_id: uuid.UUID, db: Session = Depends(get_db)):
    _project(db, project_id); return get_design_state(db, project_id)

@router.put("/projects/{project_id}/design", response_model=DesignStateRead)
def put_design(project_id: uuid.UUID, data: DesignStateUpdate, db: Session = Depends(get_db)):
    _project(db, project_id)
    obj = update_design_state(db, project_id, data.state.model_dump(), data.change_summary)
    db.commit(); db.refresh(obj); return obj

@router.patch("/projects/{project_id}/design/edit", response_model=DesignStateRead)
def patch_design(project_id: uuid.UUID, data: SurgicalEdit, db: Session = Depends(get_db)):
    _project(db, project_id)
    obj = surgical_edit(db, project_id, data.path, data.value, data.change_summary)
    db.commit(); db.refresh(obj); return obj

@router.get("/projects/{project_id}/versions", response_model=list[VersionRead])
def list_versions(project_id: uuid.UUID, db: Session = Depends(get_db)):
    _project(db, project_id)
    return list(db.scalars(select(DesignVersion).where(DesignVersion.project_id == project_id).order_by(DesignVersion.version_number.desc())))

@router.get("/projects/{project_id}/versions/{version_id}", response_model=VersionRead)
def read_version(project_id: uuid.UUID, version_id: uuid.UUID, db: Session = Depends(get_db)):
    _project(db, project_id); return get_version(db, project_id, version_id)

@router.get("/projects/{project_id}/versions/compare/{left_id}/{right_id}", response_model=VersionComparison)
def compare_version_route(project_id: uuid.UUID, left_id: uuid.UUID, right_id: uuid.UUID, db: Session = Depends(get_db)):
    _project(db, project_id); left = get_version(db, project_id, left_id); right = get_version(db, project_id, right_id)
    return {"from_version": left, "to_version": right, "changes": compare_versions(left, right)}

@router.post("/projects/{project_id}/versions/{version_id}/restore", response_model=DesignStateRead)
def restore_version_route(project_id: uuid.UUID, version_id: uuid.UUID, db: Session = Depends(get_db)):
    version = get_version(db, project_id, version_id); obj = restore_version(db, project_id, version)
    db.commit(); db.refresh(obj); return obj

@router.post("/projects/{project_id}/decisions", response_model=DecisionRead, status_code=201)
def post_decision(project_id: uuid.UUID, data: DecisionCreate, db: Session = Depends(get_db)):
    obj = record_decision(db, project_id, data); db.commit(); db.refresh(obj); return obj

@router.get("/projects/{project_id}/decisions", response_model=list[DecisionRead])
def list_decisions(project_id: uuid.UUID, db: Session = Depends(get_db)):
    _project(db, project_id); return list(db.scalars(select(DesignDecision).where(DesignDecision.project_id == project_id).order_by(DesignDecision.created_at.desc())))

@router.post("/projects/{project_id}/laws", response_model=DesignLawRead, status_code=201)
def post_law(project_id: uuid.UUID, data: DesignLawCreate, db: Session = Depends(get_db)):
    obj = create_design_law(db, project_id, data); db.commit(); db.refresh(obj); return obj

@router.get("/projects/{project_id}/laws", response_model=list[DesignLawRead])
def list_laws(project_id: uuid.UUID, db: Session = Depends(get_db)):
    _project(db, project_id); return list(db.scalars(select(DesignLaw).where(DesignLaw.project_id == project_id).order_by(DesignLaw.created_at.desc())))

@router.patch("/projects/{project_id}/laws/{law_id}", response_model=DesignLawRead)
def patch_law(project_id: uuid.UUID, law_id: uuid.UUID, data: DesignLawUpdate, db: Session = Depends(get_db)):
    _project(db, project_id)
    law = update_design_law(db, project_id, law_id, data)
    db.commit(); db.refresh(law); return law

@router.post("/projects/{project_id}/memory", response_model=MemoryRead, status_code=201)
def post_memory(project_id: uuid.UUID, data: MemoryCreate, db: Session = Depends(get_db)):
    obj = store_memory(db, project_id, data); db.commit(); db.refresh(obj); return obj

@router.get("/projects/{project_id}/memory", response_model=list[MemoryRead])
def list_memory(project_id: uuid.UUID, db: Session = Depends(get_db)):
    return get_project_memory(db, project_id)
