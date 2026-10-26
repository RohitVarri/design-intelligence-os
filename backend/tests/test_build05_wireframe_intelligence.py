"""BUILD 05 wireframe contracts and controlled lifecycle tests."""
import importlib.util
from pathlib import Path
import uuid

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from app.core.dependencies import get_provider_runtime
from app.main import app
from app.providers.contracts import ProviderResult, TaskType
from app.providers.fakes import FakeModelProvider
from app.providers.router import ModelRouter, ProviderRegistration
from app.providers.runtime import ProviderRuntime, RuntimePolicy
from app.schemas.wireframe import WireframeOutput
from app.services.wireframes import WireframeWorkflow


MIGRATION_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0005_wireframe_intelligence.py"
SPEC = importlib.util.spec_from_file_location("build05_migration", MIGRATION_PATH)
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)
BUILD03_MIGRATION_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0003_intelligence_runtime.py"
BUILD03_SPEC = importlib.util.spec_from_file_location("build03_migration", BUILD03_MIGRATION_PATH)
build03_migration = importlib.util.module_from_spec(BUILD03_SPEC)
BUILD03_SPEC.loader.exec_module(build03_migration)


def _runtime(provider=None):
    provider = provider or FakeModelProvider()
    router = ModelRouter([ProviderRegistration(
        provider, "test-model", frozenset({TaskType.DESIGN_PLAN_GENERATION, TaskType.WIREFRAME_GENERATION}),
        frozenset({"structured_output"}),
    )])
    return ProviderRuntime(router, RuntimePolicy(timeout_seconds=1, retries_per_provider=0, max_fallback_providers=0)), provider


def _approved_plan(client):
    project = client.post("/api/v1/projects", json={"name": "Wireframe test"}).json()
    project_id = project["id"]
    response = client.post(f"/api/v1/projects/{project_id}/intent", json={
        "raw_request": "Build a web product for teams to compare options and start a trial"
    })
    assert response.status_code == 201, response.text
    response = client.put(f"/api/v1/projects/{project_id}/intent", json={
        "project_type": "web application", "business_or_product_goal": "Help teams compare options",
        "primary_audience": "Small teams", "desired_user_action": "Compare and start a trial",
        "platform": "web", "required_pages": ["Home", "Pricing"],
        "required_features": ["comparison", "trial registration"],
    })
    assert response.status_code == 200, response.text
    direction = client.post(f"/api/v1/projects/{project_id}/directions", json={"generate": True}).json()[0]
    response = client.post(f"/api/v1/projects/{project_id}/directions/{direction['id']}/select", json={"confirm": True})
    assert response.status_code == 200, response.text
    candidate = client.post(f"/api/v1/projects/{project_id}/design-plan/propose")
    assert candidate.status_code == 200, candidate.text
    operation = client.post(f"/api/v1/projects/{project_id}/design-plan/candidates/{candidate.json()['candidate_id']}/operation")
    assert operation.status_code == 201, operation.text
    op_id = operation.json()["id"]
    preview = client.post(f"/api/v1/projects/{project_id}/operations/{op_id}/preview").json()
    response = client.post(f"/api/v1/projects/{project_id}/operations/{op_id}/approve", json={"preview_id": preview["id"], "approved": True})
    assert response.status_code == 200, response.text
    response = client.post(f"/api/v1/projects/{project_id}/operations/{op_id}/apply")
    assert response.status_code == 200, response.text
    return project_id


def test_wireframe_output_is_strict_and_bounded():
    with pytest.raises(ValidationError):
        WireframeOutput.model_validate({"pages": [], "rationale": "x", "confidence": 0.5, "unexpected": True}, strict=True)
    with pytest.raises(ValidationError):
        WireframeOutput.model_validate({"pages": [], "rationale": "x", "confidence": 1.2}, strict=True)


def test_wireframe_candidate_is_proposal_only_then_applies_with_history(client):
    runtime, _ = _runtime()
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    project_id = _approved_plan(client)
    before = client.get(f"/api/v1/projects/{project_id}/design").json()
    candidate = client.post(f"/api/v1/projects/{project_id}/wireframes/propose")
    assert candidate.status_code == 200, candidate.text
    result = candidate.json()
    assert result["accepted"] and result["candidate"]["pages"]
    plan = client.get(f"/api/v1/projects/{project_id}/design-plan").json()
    assert {page["page_id"] for page in result["candidate"]["pages"]} == {page["id"] for page in plan["plan"]["pages"]}
    after_proposal = client.get(f"/api/v1/projects/{project_id}/design").json()
    assert after_proposal["state"] == before["state"]
    assert after_proposal["current_version_id"] == before["current_version_id"]

    operation = client.post(f"/api/v1/projects/{project_id}/wireframes/candidates/{result['candidate_id']}/operation")
    assert operation.status_code == 201, operation.text
    op_id = operation.json()["id"]
    preview = client.post(f"/api/v1/projects/{project_id}/operations/{op_id}/preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["impact"]["requires_user_approval"] is True
    response = client.post(f"/api/v1/projects/{project_id}/operations/{op_id}/approve", json={"preview_id": preview.json()["id"], "approved": True})
    assert response.status_code == 200, response.text
    applied = client.post(f"/api/v1/projects/{project_id}/operations/{op_id}/apply")
    assert applied.status_code == 200, applied.text
    artifact = client.get(f"/api/v1/projects/{project_id}/wireframes")
    assert artifact.status_code == 200
    assert artifact.json()["status"] == "approved"
    assert artifact.json()["approved_by"] == "test-user"
    state = client.get(f"/api/v1/projects/{project_id}/design").json()
    assert state["state"]["wireframes"]["record_id"] == artifact.json()["id"]
    versions = client.get(f"/api/v1/projects/{project_id}/versions").json()
    assert any(row["id"] == state["current_version_id"] for row in versions)
    memory = client.get(f"/api/v1/projects/{project_id}/memory")
    assert memory.status_code == 200
    assert any(item["category"] == "wireframe_set" and item["trust"] == "user_approved" for item in memory.json())


def test_wireframe_candidate_is_rejected_when_approved_plan_changes(client):
    runtime, _ = _runtime()
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    project_id = _approved_plan(client)
    candidate = client.post(f"/api/v1/projects/{project_id}/wireframes/propose").json()
    state = client.get(f"/api/v1/projects/{project_id}/design").json()["state"]
    plan_record_id = state["design_plan"]["record_id"]
    from app.models.design_plan import DesignPlan
    from app.core.database import get_db
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        plan = db.get(DesignPlan, uuid.UUID(plan_record_id))
        plan.plan = {**plan.plan, "rationale": "Changed after wireframe generation"}
        db.commit()
    finally:
        db_generator.close()
    response = client.post(f"/api/v1/projects/{project_id}/wireframes/candidates/{candidate['candidate_id']}/operation")
    assert response.status_code == 409
    assert "content changed" in response.json()["detail"].lower()


def test_semantically_invalid_wireframe_is_quarantined(client):
    runtime, _ = _runtime()
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    project_id = _approved_plan(client)
    invalid = {"pages": [{
        "page_id": "not-in-plan", "layout_summary": "A page", "regions": [{
            "id": "region-1", "name": "Main", "purpose": "Content", "hierarchy_order": 1,
            "content_elements": ["Content"], "component_refs": [], "interactions": [],
        }], "responsive_notes": [], "accessibility_notes": [], "rationale": "Candidate page",
    }], "rationale": "Invalid page coverage", "confidence": 0.5}
    runtime, _ = _runtime(FakeModelProvider(responses={TaskType.WIREFRAME_GENERATION: [ProviderResult(invalid)]}))
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    result = client.post(f"/api/v1/projects/{project_id}/wireframes/propose")
    assert result.status_code == 200, result.text
    assert result.json()["accepted"] is False
    assert result.json()["status"] == "malformed"
    operation = client.post(f"/api/v1/projects/{project_id}/wireframes/candidates/{result.json()['candidate_id']}/operation")
    assert operation.status_code == 404


def test_new_approved_plan_supersedes_wireframes_from_previous_plan(client):
    runtime, _ = _runtime()
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    project_id = _approved_plan(client)
    wireframe_candidate = client.post(f"/api/v1/projects/{project_id}/wireframes/propose").json()
    wireframe_operation = client.post(f"/api/v1/projects/{project_id}/wireframes/candidates/{wireframe_candidate['candidate_id']}/operation").json()
    wireframe_op_id = wireframe_operation["id"]
    preview = client.post(f"/api/v1/projects/{project_id}/operations/{wireframe_op_id}/preview").json()
    client.post(f"/api/v1/projects/{project_id}/operations/{wireframe_op_id}/approve", json={"preview_id": preview["id"], "approved": True})
    assert client.post(f"/api/v1/projects/{project_id}/operations/{wireframe_op_id}/apply").status_code == 200
    assert client.get(f"/api/v1/projects/{project_id}/wireframes").status_code == 200

    plan_candidate = client.post(f"/api/v1/projects/{project_id}/design-plan/propose").json()
    plan_operation = client.post(f"/api/v1/projects/{project_id}/design-plan/candidates/{plan_candidate['candidate_id']}/operation").json()
    plan_op_id = plan_operation["id"]
    preview = client.post(f"/api/v1/projects/{project_id}/operations/{plan_op_id}/preview").json()
    client.post(f"/api/v1/projects/{project_id}/operations/{plan_op_id}/approve", json={"preview_id": preview["id"], "approved": True})
    assert client.post(f"/api/v1/projects/{project_id}/operations/{plan_op_id}/apply").status_code == 200
    assert client.get(f"/api/v1/projects/{project_id}/wireframes").status_code == 404
    state = client.get(f"/api/v1/projects/{project_id}/design").json()["state"]
    assert state["wireframes"] == {}


def test_wireframe_semantic_validation_requires_exact_plan_page_coverage():
    fake_plan = type("Plan", (), {"plan": {"pages": [{"id": "home"}, {"id": "pricing"}]}})()
    invalid = {"pages": [{"page_id": "home"}], "rationale": "missing page", "confidence": 0.5}
    with pytest.raises(HTTPException) as exc:
        WireframeWorkflow._validate_semantics(fake_plan, invalid)
    assert exc.value.status_code == 422


def test_build05_migration_lineage_and_constraints():
    assert migration.revision == "0005_wireframe_intelligence"
    assert migration.down_revision == "0004_design_reasoning"
    assert migration.WIREFRAME_STATUSES == ("proposed", "previewed", "approved", "rejected", "superseded")
    from app.models.wireframe import WireframeSet
    constraints = {constraint.name for constraint in WireframeSet.__table__.constraints}
    assert {"fk_wireframe_sets_plan_project", "fk_wireframe_sets_intent_revision", "fk_wireframe_sets_direction_project", "uq_wireframe_set_candidate"} <= constraints


def test_build03_migration_does_not_precreate_future_tables():
    from app.models.design_plan import DesignPlan
    from app.models.wireframe import WireframeSet
    selected = build03_migration._new_tables(set(), [DesignPlan.__table__, WireframeSet.__table__])
    assert selected == []
