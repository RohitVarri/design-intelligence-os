"""BUILD 03 provider, provenance, and controlled-operation acceptance tests."""
import asyncio
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.actors import ActorContext, ActorType, AuthorizationPolicy
from app.core.database import Base
from app.models.ai_run import AIRun, AIRunStatus
from app.models.decision import DesignDecision
from app.models.direction import DesignDirection, DirectionStatus
from app.models.design_state import DesignState
from app.models.intent import ProjectIntent
from app.models.intent import IntentStatus
from app.models.memory import DesignMemory
from app.models.operation import DesignOperation, OperationActor, OperationSource, OperationStatus
from app.models.project import Project
from app.models.research_evidence import EvidenceSourceType, EvidenceTrust, ResearchEvidence
from app.models.research_plan import ResearchPlan, ResearchPlanStatus
from app.models.research_query import ResearchQuery, ResearchQueryPriority, ResearchQueryStatus
from app.models.research_run import ResearchAttempt, ResearchResult, ResearchRunStatus
from app.models.version import DesignVersion
from app.models.operation_records import AuditEvent
from app.models.operation_records import OperationApproval, OperationPreview
from app.schemas.intent import IntentCreate
from app.providers.contracts import ProviderResult, TaskType
from app.providers.router import ModelRouter, ProviderRegistration
from app.providers.runtime import ProviderRuntime, RuntimePolicy
from app.providers.schemas import IntentCandidateOutput, DesignProposalOutput, ResearchResultsOutput
from app.schemas.operation import OperationCreate
from app.services.design_state import create_initial_design_state
from app.services.intent import IntentExtractionService
from app.services.operation_executor import OperationExecutor
from app.services.research_execution import ResearchExecutionService
from app.services.directions import direction_service
from app.core.actors import get_actor_context
from app.main import app as fastapi_app
from fastapi.testclient import TestClient


class Provider:
    def __init__(self, name, payload=None, delay=0, fail=False):
        self.name, self.payload, self.delay, self.fail = name, payload, delay, fail
        self.capabilities = frozenset({"json"})
        self.available = True

    async def generate(self, *, task, model, payload):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise ConnectionError("temporary provider outage")
        return ProviderResult(self.payload, request_id=f"{self.name}-request")


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def setup_project(db):
    project = Project(name="Runtime test")
    db.add(project)
    db.flush()
    intent = IntentExtractionService().create(db, project.id, IntentCreate(raw_request="Create a website"))
    state = create_initial_design_state(db, project.id)
    db.commit()
    return project, intent, state


def registration(provider, priority=10):
    return ProviderRegistration(provider, "test-model", frozenset({TaskType.INTENT_EXTRACTION}), frozenset({"json"}), priority)


def test_router_filters_by_task_capability_and_priority():
    slow = Provider("slow")
    first = Provider("first")
    router = ModelRouter([registration(slow, 20), registration(first, 1)])
    chosen, decision = router.route(TaskType.INTENT_EXTRACTION, {"json"})
    assert chosen.provider.name == "first"
    assert decision.matched_capabilities == ("json",)
    with pytest.raises(LookupError):
        router.route(TaskType.RESEARCH_QUERY, {"json"})


def test_runtime_validates_and_persists_ai_candidate(db):
    project, intent, _ = setup_project(db)
    provider = Provider("fake", {"fields":{"primary_audience":{"value":"Designers","confidence":0.8,"uncertainty":"medium","rationale":"Not specified"}},"summary":"candidate"})
    runtime = ProviderRuntime(ModelRouter([registration(provider)]))
    result = runtime.execute_sync(db, project_id=project.id, intent_id=intent.id, task=TaskType.INTENT_EXTRACTION,
        payload={"raw_request":intent.raw_request}, output_schema=IntentCandidateOutput,
        actor=ActorContext(ActorType.AI, trusted=True))
    assert result.accepted and result.run.status == AIRunStatus.SUCCEEDED
    assert result.candidate.validation_status == "valid"
    assert db.get(ProjectIntent, intent.id).primary_audience is None


def test_runtime_quarantines_malformed_provider_output(db):
    project, intent, _ = setup_project(db)
    provider = Provider("fake", {"fields":{"unexpected":{"nope":True}}})
    runtime = ProviderRuntime(ModelRouter([registration(provider)]))
    result = runtime.execute_sync(db, project_id=project.id, intent_id=intent.id, task=TaskType.INTENT_EXTRACTION,
        payload={}, output_schema=IntentCandidateOutput, actor=ActorContext(ActorType.AI, trusted=True))
    assert not result.accepted and result.run.status == AIRunStatus.MALFORMED
    assert result.candidate.validation_status == "quarantined"
    assert db.get(ProjectIntent, intent.id).primary_audience is None


def test_runtime_falls_back_after_timeout(db):
    project, intent, _ = setup_project(db)
    bad = Provider("timeout", delay=0.05)
    good = Provider("good", {"fields":{},"summary":"ok"})
    runtime = ProviderRuntime(ModelRouter([registration(bad, 1), registration(good, 2)]), RuntimePolicy(0.01, 0, 1))
    result = runtime.execute_sync(db, project_id=project.id, intent_id=intent.id, task=TaskType.INTENT_EXTRACTION,
        payload={}, output_schema=IntentCandidateOutput, actor=ActorContext(ActorType.AI, trusted=True))
    assert result.accepted and result.run.provider == "good" and result.run.fallback_used


def test_runtime_retries_transient_provider_failure(db):
    project, intent, _ = setup_project(db)
    class FlakyProvider(Provider):
        calls = 0
        async def generate(self, *, task, model, payload):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("temporary outage")
            return ProviderResult({"fields":{},"summary":"recovered"})
    provider = FlakyProvider("flaky")
    runtime = ProviderRuntime(ModelRouter([registration(provider)]), RuntimePolicy(1, 1, 0))
    result = runtime.execute_sync(db, project_id=project.id, intent_id=intent.id, task=TaskType.INTENT_EXTRACTION,
        payload={}, output_schema=IntentCandidateOutput, actor=ActorContext(ActorType.AI, trusted=True))
    assert result.accepted and result.run.retry_count == 1 and provider.calls == 2


def test_research_execution_links_query_attempt_result_and_untrusted_evidence(db):
    project, intent, _ = setup_project(db)
    plan = ResearchPlan(project_id=project.id, intent_id=intent.id, status=ResearchPlanStatus.QUEUED)
    db.add(plan); db.flush()
    query = ResearchQuery(plan_id=plan.id, query="accessible navigation patterns", research_area="accessibility",
        reason="Check evidence", priority=ResearchQueryPriority.HIGH, status=ResearchQueryStatus.QUEUED)
    db.add(query); db.commit()
    provider = Provider("fake-research", {"results":[{"title":"Study","claim":"Keyboard navigation improves discoverability",
        "source_name":"Example Lab","source_url":"https://example.test/study","citation":{"authors":["A. Person"]},
        "evidence":"Study excerpt"}]})
    router = ModelRouter([ProviderRegistration(provider,"fake-model",frozenset({TaskType.RESEARCH_QUERY}),frozenset({"json"}))])
    run = ResearchExecutionService().execute_plan(db, project.id, plan.id, ProviderRuntime(router), ActorContext(ActorType.AI, trusted=True))
    db.commit()
    attempt = db.scalar(select(ResearchAttempt).where(ResearchAttempt.run_id == run.id))
    result = db.scalar(select(ResearchResult).where(ResearchResult.attempt_id == attempt.id))
    evidence = db.scalar(select(ResearchEvidence).where(ResearchEvidence.result_id == result.id))
    assert run.status == ResearchRunStatus.SUCCEEDED and attempt.ai_run_id is not None
    assert result.query_id == query.id and result.citation["authors"] == ["A. Person"]
    assert evidence.trust == EvidenceTrust.UNTRUSTED


def test_authorization_fails_closed_without_trusted_actor():
    with pytest.raises(HTTPException) as error:
        AuthorizationPolicy().require(ActorContext(None), "approve")
    assert error.value.status_code == 403
    with pytest.raises(HTTPException):
        AuthorizationPolicy().require(ActorContext(ActorType.AI, trusted=True), "apply")


def test_successful_operation_is_versioned_audited_and_remembered(db):
    project, intent, initial = setup_project(db)
    user = ActorContext(ActorType.USER, actor_id="reviewer", trusted=True)
    executor = OperationExecutor()
    starting_version_id = initial.current_version_id
    operation = executor.propose(db, project.id, OperationCreate(operation_type="create", target="metadata.brand", property="metadata.brand",
        new_value="NOIR", reason="User requested the brand label", intent_id=intent.id), user)
    preview = executor.preview(db, operation.id, user)
    approval = executor.approve(db, operation.id, preview.id, user)
    applied = executor.apply(db, operation.id, user)
    db.commit()
    state = db.get(DesignState, project.id)
    assert applied.status == OperationStatus.APPLIED
    assert state.state["metadata"]["brand"] == "NOIR"
    assert len(db.scalars(select(DesignVersion).where(DesignVersion.project_id == project.id)).all()) == 2
    assert db.scalar(select(DesignMemory).where(DesignMemory.source_operation_id == operation.id)).trust.value == "user_approved"
    assert len(db.scalars(select(__import__("app.models.operation_records", fromlist=["AuditEvent"]).AuditEvent).where(__import__("app.models.operation_records", fromlist=["AuditEvent"]).AuditEvent.operation_id == operation.id)).all()) >= 4
    assert starting_version_id != state.current_version_id


def test_ai_candidate_only_changes_state_after_user_approval_and_executor(db):
    project, intent, initial = setup_project(db)
    starting_version_id = initial.current_version_id
    candidate_payload = {"operation_type":"create","target":"metadata.accent","property":"metadata.accent",
        "new_value":"amber","reason":"A warm accent may improve visual hierarchy","research_ids":[]}
    provider = Provider("fake-design", candidate_payload)
    router = ModelRouter([ProviderRegistration(provider, "fake-model", frozenset({TaskType.PROPOSAL_GENERATION}), frozenset({"json"}))])
    runtime = ProviderRuntime(router)
    ai = ActorContext(ActorType.AI, actor_id="provider", trusted=True)
    user = ActorContext(ActorType.USER, actor_id="reviewer", trusted=True)
    result = runtime.execute_sync(db, project_id=project.id, intent_id=intent.id, task=TaskType.PROPOSAL_GENERATION,
        payload={"request":"Consider a warm accent"}, output_schema=DesignProposalOutput, actor=ai)
    assert result.accepted and db.get(DesignState, project.id).state["metadata"] == {}
    executor = OperationExecutor()
    proposal = executor.propose(db, project.id, OperationCreate(operation_type="create", actor=OperationActor.AI,
        source=OperationSource.AI_PROPOSAL, target=candidate_payload["target"], property=candidate_payload["property"],
        new_value=candidate_payload["new_value"], reason=candidate_payload["reason"], intent_id=intent.id,
        ai_run_id=result.run.id, provenance={"candidate_id":str(result.candidate.id),"research_ids":[]}), ai)
    assert db.get(DesignState, project.id).state["metadata"] == {}
    preview = executor.preview(db, proposal.id, user)
    assert preview.after_state["metadata"]["accent"] == "amber"
    executor.approve(db, proposal.id, preview.id, user)
    executor.apply(db, proposal.id, user)
    db.commit()
    assert db.get(DesignState, project.id).state["metadata"]["accent"] == "amber"
    assert proposal.status == OperationStatus.APPLIED
    assert db.scalar(select(DesignMemory).where(DesignMemory.source_operation_id == proposal.id)) is not None
    assert db.scalar(select(DesignDecision).where(DesignDecision.project_id == project.id)) is None
    assert starting_version_id != db.get(DesignState, project.id).current_version_id


def test_stale_or_untrusted_ai_proposal_is_rejected_without_side_effects(db):
    project, intent, state = setup_project(db)
    run = AIRun(project_id=project.id, intent_id=intent.id, task_type="proposal_generation", provider="fake", model="fake-model",
        status=AIRunStatus.SUCCEEDED, routing_decision={}, context_references={}, provenance={})
    evidence = ResearchEvidence(project_id=project.id, intent_id=intent.id, title="External", claim="Claim", evidence="Text",
        source_type=EvidenceSourceType.OTHER, trust=EvidenceTrust.UNTRUSTED, provenance={})
    db.add_all([run,evidence]); db.flush()
    IntentExtractionService().create(db, project.id, IntentCreate(raw_request="Create a website for a new audience"))
    ai = ActorContext(ActorType.AI, actor_id="fake-provider", trusted=True)
    executor = OperationExecutor()
    operation = executor.propose(db, project.id, OperationCreate(operation_type="update", actor=OperationActor.AI,
        source=OperationSource.AI_PROPOSAL, target="metadata.brand", property="metadata.brand", new_value="Unreviewed",
        reason="Model suggestion", intent_id=intent.id, ai_run_id=run.id,
        provenance={"research_ids":[str(evidence.id)]}), ai)
    with pytest.raises(HTTPException) as error:
        executor.preview(db, operation.id, ActorContext(None))
    executor.reject(db, operation, ActorContext(None), error.value.detail)
    db.commit()
    rejection_reason = operation.provenance["rejection"]["reason"].lower()
    assert "untrusted" in rejection_reason and "stale intent revision" in rejection_reason
    assert operation.status == OperationStatus.REJECTED
    assert db.get(DesignState, project.id).current_version_id == state.current_version_id
    assert db.scalar(select(DesignMemory).where(DesignMemory.project_id == project.id)) is None
    assert db.scalar(select(DesignDecision).where(DesignDecision.project_id == project.id)) is None
    assert db.scalar(select(AuditEvent).where(AuditEvent.operation_id == operation.id, AuditEvent.event_type == "operation.rejected")) is not None


def test_api_operation_requires_explicit_preview_approval_and_apply(client):
    response = client.post("/api/v1/projects", json={"name":"Operation API"})
    project_id = response.json()["id"]
    client.post(f"/api/v1/projects/{project_id}/design")
    proposal = client.post(f"/api/v1/projects/{project_id}/operations", json={"operation_type":"create","target":"metadata.title",
        "property":"metadata.title","new_value":"Approved title","reason":"Requested title"})
    assert proposal.status_code == 201, proposal.text
    operation_id = proposal.json()["id"]
    # A request without a trusted actor can inspect a preview but cannot approve it.
    fastapi_app.dependency_overrides[get_actor_context] = lambda: ActorContext(None)
    preview = client.post(f"/api/v1/projects/{project_id}/operations/{operation_id}/preview")
    assert preview.status_code == 200
    denied = client.post(f"/api/v1/projects/{project_id}/operations/{operation_id}/approve", json={"preview_id":preview.json()["id"],"approved":True})
    assert denied.status_code == 403
    fastapi_app.dependency_overrides[get_actor_context] = lambda: ActorContext(ActorType.USER, actor_id="test-user", trusted=True, test_only=True)
    approved = client.post(f"/api/v1/projects/{project_id}/operations/{operation_id}/approve", json={"preview_id":preview.json()["id"],"approved":True})
    assert approved.status_code == 200
    applied = client.post(f"/api/v1/projects/{project_id}/operations/{operation_id}/apply")
    assert applied.status_code == 200 and applied.json()["status"] == "applied"
    state = client.get(f"/api/v1/projects/{project_id}/design").json()["state"]
    assert state["metadata"]["title"] == "Approved title"


def test_direction_patch_cannot_select_without_controlled_operation(client):
    project = client.post("/api/v1/projects", json={"name":"Direction bypass"}).json()
    project_id = project["id"]
    intent = client.post(f"/api/v1/projects/{project_id}/intent", json={"raw_request":"Create a website"})
    assert intent.status_code == 201, intent.text
    created = client.post(f"/api/v1/projects/{project_id}/directions", json={"name":"Editorial", "description":"A hypothesis"})
    assert created.status_code == 201, created.text
    direction_id = created.json()[0]["id"]

    response = client.patch(f"/api/v1/projects/{project_id}/directions/{direction_id}", json={"status":"selected"})
    assert response.status_code == 422
    assert client.get(f"/api/v1/projects/{project_id}/directions/{direction_id}").json()["status"] == "proposed"
    assert client.get(f"/api/v1/projects/{project_id}/operations").json() == []


def _direction_for(project, intent):
    return DesignDirection(project_id=project.id, intent_id=intent.id, name="Editorial",
        description="A story-led direction", status=DirectionStatus.PROPOSED,
        visual_language={}, emotional_tone=[], strengths=[], tradeoffs=[], risks=[],
        supporting_research_ids=[], confidence=0.8, provenance={})


def test_successful_direction_selection_uses_executor_and_records_all_outputs(db):
    project, intent, initial = setup_project(db)
    initial_version_id = initial.current_version_id
    intent.status = IntentStatus.READY_FOR_DIRECTION
    direction = _direction_for(project, intent)
    db.add(direction); db.commit()
    user = ActorContext(ActorType.USER, actor_id="reviewer", trusted=True)

    selected = direction_service.select(db, project.id, direction.id, user, OperationExecutor())
    db.commit()

    state = db.get(DesignState, project.id)
    operation = db.scalar(select(DesignOperation).where(DesignOperation.project_id == project.id))
    assert selected.status == DirectionStatus.SELECTED
    assert state.current_version_id != initial_version_id
    assert state.state["direction_selection"]["direction_id"] == str(direction.id)
    assert operation.status == OperationStatus.APPLIED
    assert db.scalar(select(OperationApproval).where(OperationApproval.operation_id == operation.id)).approved
    assert db.scalar(select(OperationPreview).where(OperationPreview.operation_id == operation.id)) is not None
    assert db.scalar(select(DesignDecision).where(DesignDecision.project_id == project.id, DesignDecision.source == "user")) is not None
    memory = db.scalar(select(DesignMemory).where(DesignMemory.source_operation_id == operation.id))
    assert memory is not None and memory.trust.value == "user_approved"
    event_types = set(db.scalars(select(AuditEvent.event_type).where(AuditEvent.operation_id == operation.id)))
    assert {"operation.proposed", "operation.previewed", "operation.approved", "operation.applied"}.issubset(event_types)


def test_ai_cannot_complete_direction_selection_approval_or_apply(db):
    project, intent, initial = setup_project(db)
    initial_version_id = initial.current_version_id
    intent.status = IntentStatus.READY_FOR_DIRECTION
    direction = _direction_for(project, intent)
    db.add(direction); db.commit()
    ai = ActorContext(ActorType.AI, actor_id="provider", trusted=True)
    executor = OperationExecutor()

    run = AIRun(project_id=project.id, intent_id=intent.id, task_type=TaskType.PROPOSAL_GENERATION.value,
        provider="fake", model="fake-model", status=AIRunStatus.SUCCEEDED, routing_decision={},
        context_references={}, provenance={})
    db.add(run); db.flush()
    operation = executor.propose(db, project.id, OperationCreate(operation_type="select_direction",
        actor=OperationActor.AI, source=OperationSource.AI_PROPOSAL,
        target=f"design_direction:{direction.id}", property="status", old_value="proposed",
        new_value="selected", reason="Model suggestion", intent_id=intent.id, ai_run_id=run.id), ai)
    user = ActorContext(ActorType.USER, actor_id="reviewer", trusted=True)
    preview = executor.preview(db, operation.id, user)
    with pytest.raises(HTTPException) as error:
        executor.approve(db, operation.id, preview.id, ai)
    assert error.value.status_code == 403
    executor.approve(db, operation.id, preview.id, user)
    with pytest.raises(HTTPException) as apply_error:
        executor.apply(db, operation.id, ai)
    assert apply_error.value.status_code == 403
    db.rollback()
    assert db.get(DesignDirection, direction.id).status == DirectionStatus.PROPOSED
    assert db.get(DesignState, project.id).current_version_id == initial_version_id
    assert db.scalar(select(DesignMemory).where(DesignMemory.project_id == project.id)) is None
    assert db.scalar(select(DesignDecision).where(DesignDecision.project_id == project.id)) is None


def test_generic_direction_status_service_rejects_unvalidated_selection(db):
    project, intent, _ = setup_project(db)
    direction = _direction_for(project, intent)
    db.add(direction); db.commit()
    # model_construct bypasses Pydantic validators to exercise the service boundary.
    from app.schemas.direction import DirectionStatusUpdate
    request = DirectionStatusUpdate.model_construct(status=DirectionStatus.SELECTED)
    with pytest.raises(HTTPException) as error:
        direction_service.update_status(db, project.id, direction.id, request)
    assert error.value.status_code == 409
    assert db.get(DesignDirection, direction.id).status == DirectionStatus.PROPOSED
