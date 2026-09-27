"""BUILD 04 structured reasoning, provider, operation, and revision tests."""
import json
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.actors import ActorContext, ActorType, get_actor_context
from app.core.database import Base
from app.core.dependencies import get_provider_runtime
from app.main import app
from app.models.ai_candidate import AIOutputCandidate
from app.models.ai_run import AIRun, AIRunStatus
from app.models.design_state import DesignState
from app.models.design_law import DesignLaw
from app.models.design_plan import DesignPlan, DesignPlanStatus
from app.models.direction import DesignDirection, DirectionStatus
from app.models.intent import ProjectIntent
from app.models.memory import DesignMemory, MemoryTrust
from app.models.operation import DesignOperation, OperationStatus
from app.models.operation_records import AuditEvent
from app.models.project import Project
from app.models.question import Question, QuestionCategory, QuestionPriority, QuestionStatus
from app.models.research_evidence import EvidenceSourceType, EvidenceTrust, ResearchEvidence, TrendStage
from app.models.requirement import DesignRequirement, RequirementCategory, RequirementSource, RequirementStatus
from app.models.version import DesignVersion
from app.providers.contracts import ProviderResult, TaskType
from app.providers.fakes import FakeModelProvider
from app.providers.router import ModelRouter, ProviderRegistration
from app.providers.runtime import ProviderRuntime, RuntimePolicy
from app.schemas.design_plan import DesignPlanOutput
from app.schemas.intent import IntentCreate
from app.schemas.requirement import RequirementCreate
from app.services.design_plan_workflow import DesignPlanWorkflow
from app.services.design_plans import DeterministicDesignPlanEngine
from app.services.design_reasoning import DesignReasoningService
from app.services.design_state import create_initial_design_state
from app.services.intent import IntentExtractionService
from app.services.operation_executor import OperationExecutor
from app.services.requirements import RequirementService


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _direct_context(db: Session):
    project = Project(name="Reasoning test")
    db.add(project)
    db.flush()
    old = ProjectIntent(project_id=project.id, raw_request="Old request", completeness=0.4)
    current = ProjectIntent(project_id=project.id, revision_number=2, raw_request="Build a web product for people to compare options and start a trial.",
        project_type="web application", business_or_product_goal="Help users compare options", primary_audience="Small teams",
        desired_user_action="Compare options and start a trial", platform="web", required_pages=["Home", "Pricing"],
        required_features=["comparison", "trial registration"], completeness=0.8)
    db.add_all([old, current])
    db.flush()
    project.current_intent_id = current.id
    db.flush()
    direction = DesignDirection(project_id=project.id, intent_id=current.id, name="Editorial", description="Clear and editorial",
        status=DirectionStatus.SELECTED, visual_language={"density": "balanced"}, confidence=0.7)
    db.add(direction)
    old_req = DesignRequirement(project_id=project.id, intent_id=old.id, requirement="Old requirement", category=RequirementCategory.UX,
        source=RequirementSource.USER, rationale="Old revision", status=RequirementStatus.APPROVED)
    req = DesignRequirement(project_id=project.id, intent_id=current.id, requirement="Make comparison understandable", category=RequirementCategory.UX,
        source=RequirementSource.USER, rationale="Current revision", status=RequirementStatus.APPROVED)
    db.add_all([old_req, req])
    current_evidence = ResearchEvidence(project_id=project.id, intent_id=current.id, title="Reviewed", claim="Comparison helps users",
        evidence="Reviewed evidence", source_type=EvidenceSourceType.RESEARCH_PAPER, trend_stage=TrendStage.UNKNOWN,
        trust=EvidenceTrust.REVIEWED, provenance={})
    untrusted = ResearchEvidence(project_id=project.id, intent_id=current.id, title="Untrusted", claim="Unknown claim",
        evidence="Unreviewed material", source_type=EvidenceSourceType.OTHER, trend_stage=TrendStage.UNKNOWN,
        trust=EvidenceTrust.UNTRUSTED, provenance={})
    old_evidence = ResearchEvidence(project_id=project.id, intent_id=old.id, title="Old evidence", claim="Old claim",
        evidence="Old material", source_type=EvidenceSourceType.RESEARCH_PAPER, trend_stage=TrendStage.UNKNOWN,
        trust=EvidenceTrust.REVIEWED, provenance={})
    law = DesignLaw(project_id=project.id, title="Readable content", rule="Keep essential content readable.", active=True)
    high = Question(project_id=project.id, intent_id=current.id, question="Which team role is primary?", category=QuestionCategory.AUDIENCE,
        priority=QuestionPriority.HIGH, impact="Could alter navigation", impact_score=80, reason="Audience fit", answer_type="text",
        options=[], required=True, status=QuestionStatus.OPEN, dependencies=[], provenance={})
    low = Question(project_id=project.id, intent_id=current.id, question="Which icon style?", category=QuestionCategory.VISUAL,
        priority=QuestionPriority.LOW, impact="Minor detail", impact_score=15, reason="Low impact", answer_type="text",
        options=[], required=False, status=QuestionStatus.OPEN, dependencies=[], provenance={})
    db.add_all([current_evidence, untrusted, old_evidence, law, high, low])
    db.commit()
    return project, old, current, direction, old_req, req, current_evidence, untrusted, old_evidence, law, high, low


def _runtime(provider=None):
    provider = provider or FakeModelProvider()
    router = ModelRouter([ProviderRegistration(provider, "test-model", frozenset({TaskType.DESIGN_PLAN_GENERATION}), frozenset({"structured_output"}))])
    return ProviderRuntime(router, RuntimePolicy(timeout_seconds=1, retries_per_provider=0, max_fallback_providers=0)), provider


def _api_project(client):
    project = client.post("/api/v1/projects", json={"name": "Plan API test"}).json()
    project_id = project["id"]
    created = client.post(f"/api/v1/projects/{project_id}/intent", json={"raw_request": "Build a web app for a team to compare options and start a trial"})
    assert created.status_code == 201, created.text
    updated = client.put(f"/api/v1/projects/{project_id}/intent", json={
        "project_type": "web application", "business_or_product_goal": "Help teams choose a plan",
        "primary_audience": "Small teams", "desired_user_action": "Compare plans and start a trial", "platform": "web",
        "required_pages": ["Home", "Pricing"], "required_features": ["comparison", "trial registration"],
    })
    assert updated.status_code == 200, updated.text
    direction = client.post(f"/api/v1/projects/{project_id}/directions", json={"generate": True})
    assert direction.status_code == 201, direction.text
    direction = direction.json()[0]
    selected = client.post(f"/api/v1/projects/{project_id}/directions/{direction['id']}/select", json={"confirm": True})
    assert selected.status_code == 200, selected.text
    return project_id, direction


def _enable_provider():
    runtime, provider = _runtime()
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    return provider


def test_design_plan_output_is_strict_and_confidence_is_bounded(db):
    _, _, _, _, *_ = _direct_context(db)
    context = DesignReasoningService().build_context(db, db.scalar(select(Project.id)))
    plan = DeterministicDesignPlanEngine().generate(context)
    assert DesignPlanOutput.model_validate_json(json.dumps(plan), strict=True)
    with pytest.raises(ValidationError):
        DesignPlanOutput.model_validate_json(json.dumps({**plan, "unexpected": True}), strict=True)
    with pytest.raises(ValidationError):
        DesignPlanOutput.model_validate_json(json.dumps({**plan, "confidence": 1.1}), strict=True)


def test_reasoning_context_uses_current_intent_direction_and_revision_scoped_sources(db):
    project, old, current, direction, old_req, req, evidence, untrusted, old_evidence, law, high, low = _direct_context(db)
    context = DesignReasoningService().build_context(db, project.id)
    assert context["intent_revision_id"] == str(current.id)
    assert context["direction_id"] == str(direction.id)
    assert [item["id"] for item in context["requirements"]] == [str(req.id)]
    assert [item["id"] for item in context["research"]] == [str(evidence.id)]
    assert [item["id"] for item in context["design_laws"]] == [str(law.id)]
    assert [item["id"] for item in context["open_questions"]] == [str(high.id)]
    assert context["source_manifest"] == {
        "intent": [str(current.id)], "requirements": [str(req.id)], "research": [str(evidence.id)],
        "design_laws": [str(law.id)], "questions": [str(high.id)],
    }
    assert str(old.id) not in context["source_manifest"]["intent"]
    assert str(old_req.id) not in context["source_manifest"]["requirements"]
    assert str(old_evidence.id) not in context["source_manifest"]["research"]
    assert str(untrusted.id) not in context["source_manifest"]["research"]


def test_reasoning_requires_current_intent_and_selected_direction(db):
    project, _, current, direction, *_ = _direct_context(db)
    direction.status = DirectionStatus.PROPOSED
    db.flush()
    with pytest.raises(HTTPException) as exc:
        DesignReasoningService().build_context(db, project.id)
    assert exc.value.status_code == 409 and "selected design direction" in exc.value.detail
    project.current_intent_id = None
    db.flush()
    with pytest.raises(HTTPException) as exc:
        DesignReasoningService().build_context(db, project.id)
    assert exc.value.status_code == 409


def test_deterministic_engine_carries_laws_questions_requirements_and_trusted_research(db):
    project, _, _, _, _, req, evidence, *_ = _direct_context(db)
    context = DesignReasoningService().build_context(db, project.id)
    result = DeterministicDesignPlanEngine().generate(context)
    assert result["information_architecture"]["pages"] == ["Home", "Pricing", "Sign Up"]
    assert result["requirements_mapping"][0]["requirement_id"] == str(req.id)
    assert result["research_mapping"][0]["evidence_id"] == str(evidence.id)
    assert result["design_laws_considered"][0]["id"] == context["source_manifest"]["design_laws"][0]
    assert result["unresolved_questions"][0]["question_id"] == context["source_manifest"]["questions"][0]
    assert "conformance" in result["accessibility_strategy"]["rationale"].lower()
    assert all(value is None or "user-stated" in value for value in result["design_token_strategy"]["color_roles"].values())


def test_design_plan_provider_task_routes_to_registered_provider():
    runtime, provider = _runtime()
    _, decision = runtime.router.route(TaskType.DESIGN_PLAN_GENERATION, {"structured_output"})
    assert decision.task == TaskType.DESIGN_PLAN_GENERATION
    assert decision.provider == provider.name


def test_plan_candidate_is_persisted_without_mutating_design_state(client):
    provider = _enable_provider()
    project_id, _ = _api_project(client)
    before = client.get(f"/api/v1/projects/{project_id}/design").json()
    response = client.post(f"/api/v1/projects/{project_id}/design-plan/propose")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["accepted"] is True and result["status"] == "succeeded"
    assert result["candidate"]["pages"]
    after = client.get(f"/api/v1/projects/{project_id}/design").json()
    assert before["current_version_id"] == after["current_version_id"]
    assert before["state"] == after["state"]
    assert client.get(f"/api/v1/projects/{project_id}/design-plan").status_code == 404
    assert provider.calls == [TaskType.DESIGN_PLAN_GENERATION]


def test_malformed_plan_output_is_quarantined(client):
    runtime, _ = _runtime(FakeModelProvider(behaviors=["malformed"]))
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    project_id, _ = _api_project(client)
    response = client.post(f"/api/v1/projects/{project_id}/design-plan/propose")
    assert response.status_code == 200
    assert response.json()["accepted"] is False
    assert response.json()["status"] == "malformed"
    assert response.json()["candidate_id"] is not None
    assert client.get(f"/api/v1/projects/{project_id}/design-plan").status_code == 404


def test_design_plan_api_requires_an_explicitly_selected_direction(client):
    project = client.post("/api/v1/projects", json={"name": "No direction"}).json()
    project_id = project["id"]
    assert client.post(f"/api/v1/projects/{project_id}/intent", json={"raw_request": "Create a website"}).status_code == 201
    response = client.post(f"/api/v1/projects/{project_id}/design-plan/propose")
    assert response.status_code == 409
    assert "selected design direction" in response.json()["detail"]


def test_candidate_converts_to_ai_operation_and_successful_approval_apply(client):
    _enable_provider()
    project_id, _ = _api_project(client)
    requirement = client.post(f"/api/v1/projects/{project_id}/requirements", json={
        "requirement": "Make plan comparison understandable", "category": "UX", "source": "user", "rationale": "User asked for comparison"
    })
    law = client.post(f"/api/v1/projects/{project_id}/laws", json={"title": "Legibility", "rule": "Keep comparison text readable."})
    assert requirement.status_code == law.status_code == 201
    response = client.post(f"/api/v1/projects/{project_id}/design-plan/propose")
    candidate_id = response.json()["candidate_id"]
    created = client.post(f"/api/v1/projects/{project_id}/design-plan/candidates/{candidate_id}/operation")
    assert created.status_code == 201, created.text
    operation = created.json()
    assert operation["operation_type"] == "create" and operation["actor"] == "ai" and operation["status"] == "proposed"
    assert operation["target"] == "metadata.design_plan"
    assert operation["candidate_id"] == candidate_id
    before = client.get(f"/api/v1/projects/{project_id}/design").json()
    preview = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/preview")
    assert preview.status_code == 200, preview.text
    after_preview = client.get(f"/api/v1/projects/{project_id}/design").json()
    assert after_preview["current_version_id"] == before["current_version_id"]
    approval = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/approve", json={"preview_id": preview.json()["id"], "approved": True})
    assert approval.status_code == 200, approval.text
    applied = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/apply")
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    plan = client.get(f"/api/v1/projects/{project_id}/design-plan")
    assert plan.status_code == 200 and plan.json()["status"] == "approved"
    assert plan.json()["provenance"]["source_type"] == "ai_design_reasoning"
    assert plan.json()["provenance"]["requirement_ids"] == [requirement.json()["id"]]
    assert plan.json()["provenance"]["design_law_ids"] == [law.json()["id"]]
    state = client.get(f"/api/v1/projects/{project_id}/design").json()
    stored = state["state"]["design_plan"]
    assert stored["plan"]["pages"]
    assert stored["approved_by"] == "test-user"
    versions = client.get(f"/api/v1/projects/{project_id}/versions").json()
    assert len(versions) >= 3 and any(row["id"] == before["current_version_id"] for row in versions)
    memory = client.get(f"/api/v1/projects/{project_id}/memory").json()
    assert any(item["category"] == "design_plan" and item["trust"] == "user_approved" for item in memory)


def test_new_plan_supersedes_previous_approved_plan_and_preserves_version_history(client):
    _enable_provider()
    project_id, _ = _api_project(client)
    old_id = None
    for _ in range(2):
        candidate = client.post(f"/api/v1/projects/{project_id}/design-plan/propose").json()
        operation = client.post(f"/api/v1/projects/{project_id}/design-plan/candidates/{candidate['candidate_id']}/operation").json()
        preview = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/preview").json()
        assert client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/approve", json={"preview_id": preview["id"], "approved": True}).status_code == 200
        assert client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/apply").status_code == 200
        latest = client.get(f"/api/v1/projects/{project_id}/design-plan").json()
        if old_id is None:
            old_id = latest["id"]
    assert latest["id"] != old_id
    assert latest["status"] == "approved"


def test_rejected_plan_does_not_change_state(client):
    _enable_provider()
    project_id, _ = _api_project(client)
    candidate = client.post(f"/api/v1/projects/{project_id}/design-plan/propose").json()
    operation = client.post(f"/api/v1/projects/{project_id}/design-plan/candidates/{candidate['candidate_id']}/operation").json()
    before = client.get(f"/api/v1/projects/{project_id}/design").json()
    preview = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/preview").json()
    reject = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/approve", json={"preview_id": preview["id"], "approved": False})
    assert reject.status_code == 200
    after = client.get(f"/api/v1/projects/{project_id}/design").json()
    assert after["state"] == before["state"] and after["current_version_id"] == before["current_version_id"]
    assert client.get(f"/api/v1/projects/{project_id}/design-plan").status_code == 404


def test_stale_intent_candidate_rejected_at_preview_without_state_mutation(client):
    _enable_provider()
    project_id, _ = _api_project(client)
    candidate = client.post(f"/api/v1/projects/{project_id}/design-plan/propose").json()
    operation = client.post(f"/api/v1/projects/{project_id}/design-plan/candidates/{candidate['candidate_id']}/operation").json()
    before = client.get(f"/api/v1/projects/{project_id}/design").json()
    changed = client.put(f"/api/v1/projects/{project_id}/intent", json={"business_or_product_goal": "A revised goal"})
    assert changed.status_code == 200
    preview = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/preview")
    assert preview.status_code == 409
    after = client.get(f"/api/v1/projects/{project_id}/design").json()
    assert after["current_version_id"] == before["current_version_id"]
    assert "stale intent" in preview.json()["detail"].lower()


def test_stale_selected_direction_candidate_rejected_at_preview(client):
    _enable_provider()
    project_id, _ = _api_project(client)
    candidate = client.post(f"/api/v1/projects/{project_id}/design-plan/propose").json()
    operation = client.post(f"/api/v1/projects/{project_id}/design-plan/candidates/{candidate['candidate_id']}/operation").json()
    new_direction = client.post(f"/api/v1/projects/{project_id}/directions", json={"name": "Alternate", "description": "Alternative direction"}).json()[0]
    assert client.post(f"/api/v1/projects/{project_id}/directions/{new_direction['id']}/select", json={"confirm": True}).status_code == 200
    before_preview = client.get(f"/api/v1/projects/{project_id}/design").json()
    preview = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/preview")
    assert preview.status_code == 409
    assert "direction" in preview.json()["detail"].lower()
    after_preview = client.get(f"/api/v1/projects/{project_id}/design").json()
    assert after_preview["current_version_id"] == before_preview["current_version_id"]


def test_research_revoked_after_generation_is_rejected_at_preview(client):
    _enable_provider()
    project_id, _ = _api_project(client)
    evidence = client.post(f"/api/v1/projects/{project_id}/research", json={"title": "Reviewed evidence", "claim": "Comparison supports informed choice", "source_type": "research_paper", "evidence": "A reviewed finding"}).json()
    reviewed = client.post(f"/api/v1/projects/{project_id}/research/{evidence['id']}/review", json={"eligible": True, "rationale": "Relevant to current intent"})
    assert reviewed.status_code == 200
    candidate = client.post(f"/api/v1/projects/{project_id}/design-plan/propose").json()
    operation = client.post(f"/api/v1/projects/{project_id}/design-plan/candidates/{candidate['candidate_id']}/operation").json()
    revoked = client.post(f"/api/v1/projects/{project_id}/research/{evidence['id']}/review", json={"eligible": False, "rationale": "No longer trusted"})
    assert revoked.status_code == 200
    before_preview = client.get(f"/api/v1/projects/{project_id}/design").json()
    preview = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/preview")
    assert preview.status_code == 409
    assert "untrusted" in preview.json()["detail"].lower()
    after_preview = client.get(f"/api/v1/projects/{project_id}/design").json()
    assert after_preview["current_version_id"] == before_preview["current_version_id"]


def test_ai_cannot_approve_or_apply_design_plan_operation(client):
    _enable_provider()
    project_id, _ = _api_project(client)
    candidate = client.post(f"/api/v1/projects/{project_id}/design-plan/propose").json()
    operation = client.post(f"/api/v1/projects/{project_id}/design-plan/candidates/{candidate['candidate_id']}/operation").json()
    preview = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/preview").json()
    app.dependency_overrides[get_actor_context] = lambda: ActorContext(ActorType.AI, actor_id="ai", trusted=True)
    denied = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/approve", json={"preview_id": preview["id"], "approved": True})
    assert denied.status_code == 403
    denied_apply = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/apply")
    assert denied_apply.status_code == 403


def test_requirement_generation_is_scoped_to_each_intent_revision(db):
    project = Project(name="Requirements revisions")
    db.add(project)
    db.flush()
    first = ProjectIntent(project_id=project.id, raw_request="Build a product for teams to compare tools and start trial.",
        business_or_product_goal="Compare tools", desired_user_action="Start a trial", visual_preferences=["editorial"])
    db.add(first); db.flush(); project.current_intent_id = first.id; db.flush()
    service = RequirementService()
    first_rows = service.generate_from_intent(db, project.id)
    assert first_rows and all(row.intent_id == first.id for row in first_rows)
    second = ProjectIntent(project_id=project.id, revision_number=2, raw_request="Build a booking site for local studios.",
        business_or_product_goal="Book a studio", desired_user_action="Reserve a room", visual_preferences=["bright"])
    db.add(second); db.flush(); project.current_intent_id = second.id; db.flush()
    second_rows = service.generate_from_intent(db, project.id)
    assert second_rows and all(row.intent_id == second.id for row in second_rows)
    assert {row.id for row in first_rows}.isdisjoint({row.id for row in second_rows})
    assert all(row.requirement not in {first_row.requirement for first_row in first_rows} for row in second_rows)
    assert len(db.scalars(select(DesignRequirement).where(DesignRequirement.project_id == project.id)).all()) == len(first_rows) + len(second_rows)


def test_design_law_is_a_read_only_source_and_state_does_not_receive_ai_mutations(client):
    _enable_provider()
    project_id, _ = _api_project(client)
    law = client.post(f"/api/v1/projects/{project_id}/laws", json={"title": "Contrast", "rule": "Keep text legible against its background."})
    assert law.status_code == 201
    before = client.get(f"/api/v1/projects/{project_id}/design").json()
    proposal = client.post(f"/api/v1/projects/{project_id}/design-plan/propose").json()
    assert law.json()["id"] == proposal["candidate"]["design_laws_considered"][0]["id"]
    after = client.get(f"/api/v1/projects/{project_id}/design").json()
    assert after["current_version_id"] == before["current_version_id"]


def test_candidate_to_operation_validation_rejects_unknown_or_wrong_revision_requirement(db):
    project, old, current, direction, old_req, req, *_ = _direct_context(db)
    context = DesignReasoningService().build_context(db, project.id)
    output = DeterministicDesignPlanEngine().generate(context)
    run = AIRun(project_id=project.id, intent_id=current.id, task_type=TaskType.DESIGN_PLAN_GENERATION.value,
        provider="fake", model="model", status=AIRunStatus.SUCCEEDED,
        context_references={"source_manifest": context["source_manifest"], "direction_id": context["direction_id"]})
    db.add(run); db.flush()
    candidate = AIOutputCandidate(run_id=run.id, project_id=project.id, intent_id=current.id, candidate_type=TaskType.DESIGN_PLAN_GENERATION.value,
        schema_version="1", payload=output, validation_status="valid", provenance={})
    db.add(candidate); db.flush()
    manifest = {key: list(value) for key, value in context["source_manifest"].items()}
    manifest["requirements"].append(str(old_req.id))
    run.context_references = {"source_manifest": manifest, "direction_id": context["direction_id"]}
    plan = DesignPlan(project_id=project.id, intent_id=current.id, direction_id=direction.id, candidate_id=candidate.id,
        status=DesignPlanStatus.PROPOSED, plan=output, confidence=output["confidence"], provenance={"source_manifest": manifest})
    db.add(plan); db.flush()
    from app.schemas.operation import OperationCreate
    data = OperationCreate(operation_type="create", actor="ai", target="metadata.design_plan", property="metadata.design_plan",
        new_value={"plan": output, "intent_revision_id": str(current.id), "direction_id": str(direction.id)},
        reason="Plan proposal", source="ai_proposal", intent_id=current.id, ai_run_id=run.id, candidate_id=candidate.id,
        direction_id=direction.id, provenance={"source_manifest": manifest,
            "requirement_ids": manifest["requirements"], "research_ids": manifest["research"]})
    executor = OperationExecutor()
    operation = executor.propose(db, project.id, data, ActorContext(ActorType.AI, actor_id="runtime", trusted=True))
    with pytest.raises(HTTPException) as exc:
        executor.validate(db, operation)
    assert exc.value.status_code == 409
    assert "requirement" in exc.value.detail.lower()


def _direct_operation(db: Session, project_id: uuid.UUID):
    context = DesignReasoningService().build_context(db, project_id)
    output = DeterministicDesignPlanEngine().generate(context)
    intent_id = uuid.UUID(context["intent_revision_id"])
    direction_id = uuid.UUID(context["direction_id"])
    run = AIRun(project_id=project_id, intent_id=intent_id, task_type=TaskType.DESIGN_PLAN_GENERATION.value,
        provider="fake", model="model", status=AIRunStatus.SUCCEEDED,
        context_references={"source_manifest": context["source_manifest"], "direction_id": str(direction_id)})
    db.add(run); db.flush()
    candidate = AIOutputCandidate(run_id=run.id, project_id=project_id, intent_id=intent_id,
        candidate_type=TaskType.DESIGN_PLAN_GENERATION.value, schema_version="1", payload=output,
        validation_status="valid", provenance={"source_manifest": context["source_manifest"]})
    db.add(candidate); db.flush()
    record = DesignPlan(project_id=project_id, intent_id=intent_id, direction_id=direction_id, candidate_id=candidate.id,
        status=DesignPlanStatus.PROPOSED, plan=output, confidence=output["confidence"],
        provenance={"source_manifest": context["source_manifest"], "source_type": "ai_design_reasoning"})
    db.add(record); db.flush()
    from app.schemas.operation import OperationCreate
    data = OperationCreate(operation_type="create", actor="ai", target="metadata.design_plan", property="metadata.design_plan",
        new_value={"plan": output, "intent_revision_id": str(intent_id), "direction_id": str(direction_id), "provenance": record.provenance},
        reason="Plan proposal", source="ai_proposal", intent_id=intent_id, ai_run_id=run.id,
        candidate_id=candidate.id, direction_id=direction_id,
        provenance={"source_manifest": context["source_manifest"],
            "requirement_ids": context["source_manifest"]["requirements"], "research_ids": context["source_manifest"]["research"]})
    actor_ai = ActorContext(ActorType.AI, actor_id="runtime", trusted=True)
    operation = OperationExecutor().propose(db, project_id, data, actor_ai)
    return operation, record


def test_executor_creates_version_audit_and_approved_memory_atomically_and_is_idempotent(db):
    project, *_ = _direct_context(db)
    initial = create_initial_design_state(db, project.id)
    db.commit()
    original_version_id = initial.current_version_id
    operation, record = _direct_operation(db, project.id)
    executor = OperationExecutor()
    reviewer = ActorContext(ActorType.USER, actor_id="reviewer", trusted=True)
    preview = executor.preview(db, operation.id, reviewer)
    assert db.get(DesignState, project.id).current_version_id == original_version_id
    executor.approve(db, operation.id, preview.id, reviewer, True)
    applied = executor.apply(db, operation.id, reviewer)
    db.flush()
    state = db.get(DesignState, project.id)
    assert applied.status == OperationStatus.APPLIED
    assert state.current_version_id != original_version_id
    original_version = db.get(DesignVersion, original_version_id)
    assert original_version is not None and not original_version.state.get("design_plan")
    assert db.get(DesignPlan, record.id).status == DesignPlanStatus.APPROVED
    events = db.scalars(select(AuditEvent).where(AuditEvent.operation_id == operation.id)).all()
    assert {event.event_type for event in events} >= {"operation.proposed", "operation.previewed", "operation.approved", "operation.applied"}
    memories = db.scalars(select(DesignMemory).where(DesignMemory.source_operation_id == operation.id)).all()
    assert len(memories) == 1 and memories[0].trust == MemoryTrust.USER_APPROVED
    assert memories[0].provenance["direction_id"] == str(record.direction_id)
    assert memories[0].provenance["source_manifest"]
    executor.apply(db, operation.id, reviewer)
    db.flush()
    assert len(db.scalars(select(DesignMemory).where(DesignMemory.source_operation_id == operation.id)).all()) == 1

    second_operation, second_record = _direct_operation(db, project.id)
    second_preview = executor.preview(db, second_operation.id, reviewer)
    executor.approve(db, second_operation.id, second_preview.id, reviewer, True)
    executor.apply(db, second_operation.id, reviewer)
    db.flush()
    assert db.get(DesignPlan, record.id).status == DesignPlanStatus.SUPERSEDED
    assert db.get(DesignPlan, second_record.id).status == DesignPlanStatus.APPROVED
    assert len(db.scalars(select(DesignMemory).where(DesignMemory.project_id == project.id, DesignMemory.category == "design_plan")).all()) == 2
