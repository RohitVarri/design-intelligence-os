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
from app.models.intent import ProjectIntent
from app.models.question import Question, QuestionStatus
from app.models.research_query import ResearchQuery
from app.models.research_plan import ResearchPlan
from app.models.research_evidence import ResearchEvidence
from app.models.requirement import DesignRequirement
from app.models.direction import DesignDirection
from app.models.direction_assessment import DesignDirectionAssessment
from app.models.operation import DesignOperation
from app.schemas.intent import IntentCreate, IntentUpdate, IntentRead, IntentAnalysisRead
from app.schemas.question import QuestionCreate, QuestionUpdate, QuestionAnswer, QuestionRead
from app.schemas.research import ResearchEvidenceCreate, ResearchEvidenceRead, ResearchPlanRead, ResearchQueryRead
from app.schemas.requirement import RequirementCreate, RequirementRead
from app.schemas.direction import DirectionCreate, DirectionRead, DirectionAssessmentCreate, DirectionAssessmentRead, DirectionStatusUpdate, DirectionSelection
from app.schemas.operation import OperationCreate, OperationRead
from app.services.intent import IntentExtractionService, intent_extraction
from app.services.questions import question_service
from app.services.research import research_service
from app.services.requirements import requirement_service
from app.services.directions import direction_service
from app.services.operations import operation_service

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

# BUILD 02: intent understanding and targeted clarification.
@router.post("/projects/{project_id}/intent", response_model=IntentRead, status_code=201)
def post_intent(project_id: uuid.UUID, data: IntentCreate, db: Session = Depends(get_db)):
    obj = intent_extraction.create(db, project_id, data)
    question_service.generate(db, project_id, obj)
    db.commit(); db.refresh(obj); return obj

@router.get("/projects/{project_id}/intent", response_model=IntentRead)
def get_intent(project_id: uuid.UUID, db: Session = Depends(get_db)):
    _project(db, project_id); return intent_extraction.latest(db, project_id)

@router.put("/projects/{project_id}/intent", response_model=IntentRead)
def put_intent(project_id: uuid.UUID, data: IntentUpdate, db: Session = Depends(get_db)):
    _project(db, project_id); obj = intent_extraction.update(db, project_id, data)
    db.commit(); db.refresh(obj); return obj

@router.post("/projects/{project_id}/intent/analyze", response_model=IntentAnalysisRead)
def analyze_intent(project_id: uuid.UUID, db: Session = Depends(get_db)):
    _project(db, project_id); obj = intent_extraction.analyze(db, project_id)
    questions = question_service.generate(db, project_id, obj)
    missing = IntentExtractionService.missing_information(obj)
    db.commit(); db.refresh(obj)
    return {"intent": obj, "missing_information": missing, "generated_questions": len(questions)}

@router.get("/projects/{project_id}/questions", response_model=list[QuestionRead])
def get_questions(project_id: uuid.UUID, db: Session = Depends(get_db)):
    return question_service.list_for_project(db, project_id)

@router.get("/projects/{project_id}/questions/open", response_model=list[QuestionRead])
def get_open_questions(project_id: uuid.UUID, db: Session = Depends(get_db)):
    return question_service.list_for_project(db, project_id, open_only=True)

@router.post("/projects/{project_id}/questions", response_model=QuestionRead, status_code=201)
def post_question(project_id: uuid.UUID, data: QuestionCreate, db: Session = Depends(get_db)):
    obj = question_service.create(db, project_id, data); db.commit(); db.refresh(obj); return obj

@router.patch("/projects/{project_id}/questions/{question_id}", response_model=QuestionRead)
def patch_question(project_id: uuid.UUID, question_id: uuid.UUID, data: QuestionUpdate, db: Session = Depends(get_db)):
    obj = question_service.update(db, project_id, question_id, status=data.status, reason=data.reason)
    db.commit(); db.refresh(obj); return obj

@router.post("/projects/{project_id}/questions/{question_id}/answer", response_model=QuestionRead)
def answer_question(project_id: uuid.UUID, question_id: uuid.UUID, data: QuestionAnswer, db: Session = Depends(get_db)):
    obj = question_service.answer(db, project_id, question_id, data.answer)
    db.commit(); db.refresh(obj); return obj

# BUILD 02: research evidence is persisted with provenance and a trust label; no live search runs.
@router.get("/projects/{project_id}/research", response_model=list[ResearchEvidenceRead])
def get_research(project_id: uuid.UUID, db: Session = Depends(get_db)):
    return research_service.list_evidence(db, project_id)

@router.post("/projects/{project_id}/research", response_model=ResearchEvidenceRead, status_code=201)
def post_research(project_id: uuid.UUID, data: ResearchEvidenceCreate, db: Session = Depends(get_db)):
    obj = research_service.store_evidence(db, project_id, data); db.commit(); db.refresh(obj); return obj

def _plan_payload(db: Session, plan: ResearchPlan):
    queries = list(db.scalars(select(ResearchQuery).where(ResearchQuery.plan_id == plan.id).order_by(ResearchQuery.created_at)))
    return {"id": plan.id, "project_id": plan.project_id, "intent_id": plan.intent_id, "status": plan.status,
        "created_at": plan.created_at, "updated_at": plan.updated_at, "queries": queries}

@router.get("/projects/{project_id}/research-plan", response_model=ResearchPlanRead)
def get_research_plan(project_id: uuid.UUID, db: Session = Depends(get_db)):
    _project(db, project_id); return _plan_payload(db, research_service.get_latest_plan(db, project_id))

@router.post("/projects/{project_id}/research-plan", response_model=ResearchPlanRead, status_code=201)
def post_research_plan(project_id: uuid.UUID, db: Session = Depends(get_db)):
    plan = research_service.create_plan(db, project_id); db.commit(); db.refresh(plan); return _plan_payload(db, plan)

# BUILD 02: requirements preserve user, inference, research, and system source.
@router.get("/projects/{project_id}/requirements", response_model=list[RequirementRead])
def get_requirements(project_id: uuid.UUID, db: Session = Depends(get_db)):
    return requirement_service.list_for_project(db, project_id)

@router.post("/projects/{project_id}/requirements", response_model=RequirementRead, status_code=201)
def post_requirement(project_id: uuid.UUID, data: RequirementCreate, db: Session = Depends(get_db)):
    obj = requirement_service.create(db, project_id, data); db.commit(); db.refresh(obj); return obj

@router.post("/projects/{project_id}/requirements/generate", response_model=list[RequirementRead], status_code=201)
def generate_requirements(project_id: uuid.UUID, db: Session = Depends(get_db)):
    rows = requirement_service.generate_from_intent(db, project_id); db.commit()
    for row in rows: db.refresh(row)
    return rows

# BUILD 02: directions are hypotheses; only the explicit select action records a human choice.
@router.get("/projects/{project_id}/directions", response_model=list[DirectionRead])
def get_directions(project_id: uuid.UUID, db: Session = Depends(get_db)):
    return direction_service.list_for_project(db, project_id)

@router.post("/projects/{project_id}/directions", response_model=list[DirectionRead], status_code=201)
def post_directions(project_id: uuid.UUID, data: DirectionCreate | None = None, db: Session = Depends(get_db)):
    obj = direction_service.create(db, project_id, data or DirectionCreate(generate=True))
    db.commit()
    for row in obj: db.refresh(row)
    return obj

@router.get("/projects/{project_id}/directions/{direction_id}", response_model=DirectionRead)
def get_direction(project_id: uuid.UUID, direction_id: uuid.UUID, db: Session = Depends(get_db)):
    _project(db, project_id); return direction_service.get(db, project_id, direction_id)

@router.post("/projects/{project_id}/directions/{direction_id}/select", response_model=DirectionRead)
def select_direction(project_id: uuid.UUID, direction_id: uuid.UUID, data: DirectionSelection, db: Session = Depends(get_db)):
    obj = direction_service.select(db, project_id, direction_id); db.commit(); db.refresh(obj); return obj

@router.patch("/projects/{project_id}/directions/{direction_id}", response_model=DirectionRead)
def patch_direction(project_id: uuid.UUID, direction_id: uuid.UUID, data: DirectionStatusUpdate, db: Session = Depends(get_db)):
    obj = direction_service.update_status(db, project_id, direction_id, data); db.commit(); db.refresh(obj); return obj

@router.get("/projects/{project_id}/directions/{direction_id}/assessments", response_model=list[DirectionAssessmentRead])
def get_direction_assessments(project_id: uuid.UUID, direction_id: uuid.UUID, db: Session = Depends(get_db)):
    return direction_service.assessments(db, project_id, direction_id)

@router.post("/projects/{project_id}/directions/{direction_id}/assessments", response_model=DirectionAssessmentRead, status_code=201)
def post_direction_assessment(project_id: uuid.UUID, direction_id: uuid.UUID, data: DirectionAssessmentCreate, db: Session = Depends(get_db)):
    obj = direction_service.assess(db, project_id, direction_id, data); db.commit(); db.refresh(obj); return obj

# BUILD 02: proposals are records only; there is intentionally no apply endpoint.
@router.get("/projects/{project_id}/operations", response_model=list[OperationRead])
def get_operations(project_id: uuid.UUID, db: Session = Depends(get_db)):
    return operation_service.list(db, project_id)

@router.post("/projects/{project_id}/operations", response_model=OperationRead, status_code=201)
def post_operation(project_id: uuid.UUID, data: OperationCreate, db: Session = Depends(get_db)):
    obj = operation_service.create_proposal(db, project_id, data); db.commit(); db.refresh(obj); return obj
