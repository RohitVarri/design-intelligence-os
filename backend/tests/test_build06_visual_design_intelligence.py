"""BUILD 06 visual-design contracts and controlled lifecycle tests."""
import importlib.util
from pathlib import Path
import uuid

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from app.core.database import get_db
from app.core.dependencies import get_provider_runtime
from app.core.actors import ActorContext, ActorType, get_actor_context
from app.main import app
from app.models.visual_design import VisualDesign
from app.providers.contracts import ProviderResult, TaskType
from app.providers.fakes import FakeModelProvider
from app.providers.router import ModelRouter, ProviderRegistration
from app.providers.runtime import ProviderRuntime, RuntimePolicy
from app.schemas.visual_design import VisualDesignOutput
from app.services.visual_designs import DeterministicVisualDesignEngine, VisualDesignWorkflow


MIGRATION_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0006_visual_design_intelligence.py"
SPEC = importlib.util.spec_from_file_location("build06_migration", MIGRATION_PATH)
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def _runtime(provider=None):
    provider = provider or FakeModelProvider()
    router = ModelRouter([ProviderRegistration(
        provider, "test-model", frozenset({
            TaskType.DESIGN_PLAN_GENERATION, TaskType.WIREFRAME_GENERATION,
            TaskType.VISUAL_DESIGN_GENERATION,
        }), frozenset({"structured_output"}),
    )])
    return ProviderRuntime(router, RuntimePolicy(timeout_seconds=1, retries_per_provider=0, max_fallback_providers=0)), provider


def _approved_sources(client):
    project = client.post("/api/v1/projects", json={"name": "Visual design test"}).json()
    project_id = project["id"]
    law = client.post(f"/api/v1/projects/{project_id}/laws", json={
        "title": "Keyboard access", "rule": "All primary actions remain keyboard accessible.",
    })
    assert law.status_code == 201, law.text
    assert client.post(f"/api/v1/projects/{project_id}/intent", json={
        "raw_request": "Build a web product for teams to compare options and start a trial"
    }).status_code == 201
    assert client.put(f"/api/v1/projects/{project_id}/intent", json={
        "project_type": "web application", "business_or_product_goal": "Help teams compare options",
        "primary_audience": "Small teams", "desired_user_action": "Compare and start a trial",
        "platform": "web", "required_pages": ["Home", "Pricing"],
        "required_features": ["comparison", "trial registration"],
    }).status_code == 200
    requirement = client.post(f"/api/v1/projects/{project_id}/requirements", json={
        "requirement": "Keep primary actions keyboard accessible.",
        "category": "accessibility", "priority": "high", "source": "user",
        "rationale": "Explicitly requested accessibility behavior.", "status": "approved", "confidence": 1.0,
    })
    assert requirement.status_code == 201, requirement.text
    direction = client.post(f"/api/v1/projects/{project_id}/directions", json={"generate": True}).json()[0]
    assert client.post(f"/api/v1/projects/{project_id}/directions/{direction['id']}/select", json={"confirm": True}).status_code == 200
    plan = client.post(f"/api/v1/projects/{project_id}/design-plan/propose")
    assert plan.status_code == 200, plan.text
    operation = client.post(f"/api/v1/projects/{project_id}/design-plan/candidates/{plan.json()['candidate_id']}/operation")
    assert operation.status_code == 201, operation.text
    _approve_and_apply(client, project_id, operation.json()["id"])
    wireframe = client.post(f"/api/v1/projects/{project_id}/wireframes/propose")
    assert wireframe.status_code == 200 and wireframe.json()["accepted"], wireframe.text
    operation = client.post(f"/api/v1/projects/{project_id}/wireframes/candidates/{wireframe.json()['candidate_id']}/operation")
    assert operation.status_code == 201, operation.text
    _approve_and_apply(client, project_id, operation.json()["id"])
    return project_id


def _approve_and_apply(client, project_id, operation_id):
    preview = client.post(f"/api/v1/projects/{project_id}/operations/{operation_id}/preview")
    assert preview.status_code == 200, preview.text
    approved = client.post(f"/api/v1/projects/{project_id}/operations/{operation_id}/approve", json={
        "preview_id": preview.json()["id"], "approved": True,
    })
    assert approved.status_code == 200, approved.text
    applied = client.post(f"/api/v1/projects/{project_id}/operations/{operation_id}/apply")
    assert applied.status_code == 200, applied.text
    return preview.json()


def _propose_visual(client, project_id):
    candidate = client.post(f"/api/v1/projects/{project_id}/visual-design/propose")
    assert candidate.status_code == 200, candidate.text
    assert candidate.json()["accepted"], candidate.text
    operation = client.post(
        f"/api/v1/projects/{project_id}/visual-design/candidates/{candidate.json()['candidate_id']}/operation"
    )
    assert operation.status_code == 201, operation.text
    return candidate.json(), operation.json()


def test_visual_design_is_proposal_only_then_applies_with_version_audit_and_memory(client):
    runtime, _ = _runtime()
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    project_id = _approved_sources(client)
    before = client.get(f"/api/v1/projects/{project_id}/design").json()
    candidate, operation = _propose_visual(client, project_id)
    assert candidate["candidate"]["pages"]
    after_proposal = client.get(f"/api/v1/projects/{project_id}/design").json()
    assert after_proposal["state"] == before["state"]
    assert after_proposal["current_version_id"] == before["current_version_id"]

    preview = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["impact"]["requires_user_approval"] is True
    assert preview.json()["impact"]["scope"] == "project"
    approved = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/approve", json={
        "preview_id": preview.json()["id"], "approved": True,
    })
    assert approved.status_code == 200, approved.text
    assert client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/apply").status_code == 200
    visual = client.get(f"/api/v1/projects/{project_id}/visual-design")
    assert visual.status_code == 200
    state = client.get(f"/api/v1/projects/{project_id}/design").json()
    assert state["state"]["visual_design"]["record_id"] == visual.json()["id"]
    for key, value in before["state"].items():
        if key != "visual_design":
            assert state["state"][key] == value
    assert client.get(f"/api/v1/projects/{project_id}/laws").json()[0]["rule"] == "All primary actions remain keyboard accessible."
    tampered_state = {**state["state"], "visual_design": {**state["state"]["visual_design"], "tampered": True}}
    generic_update = client.put(f"/api/v1/projects/{project_id}/design", json={
        "state": tampered_state, "change_summary": "Attempt generic visual overwrite",
    })
    assert generic_update.status_code == 403
    assert client.get(f"/api/v1/projects/{project_id}/design").json()["state"] == state["state"]
    forged_restore = client.post(f"/api/v1/projects/{project_id}/operations", json={
        "operation_type": "replace", "target": "*", "new_value": tampered_state,
        "reason": "Attempt to forge version restoration provenance",
        "provenance": {"restored_version_id": state["current_version_id"]},
    })
    assert forged_restore.status_code == 201, forged_restore.text
    rejected_restore = client.post(
        f"/api/v1/projects/{project_id}/operations/{forged_restore.json()['id']}/preview"
    )
    assert rejected_restore.status_code == 403
    assert client.get(f"/api/v1/projects/{project_id}/design").json()["state"] == state["state"]
    versions = client.get(f"/api/v1/projects/{project_id}/versions").json()
    assert any(row["id"] == state["current_version_id"] for row in versions)
    memory = client.get(f"/api/v1/projects/{project_id}/memory").json()
    approved_memory = next(item for item in memory if item["category"] == "visual_design")
    assert approved_memory["trust"] == "user_approved"
    assert approved_memory["provenance"]["visual_design_id"] == visual.json()["id"]
    from app.core.database import get_db as db_dependency
    from app.models.operation_records import AuditEvent
    generator = app.dependency_overrides[db_dependency]()
    db = next(generator)
    try:
        record = db.get(VisualDesign, uuid.UUID(visual.json()["id"]))
        assert record.provenance["source_manifest"]["content_digest"]
        assert record.provenance["design_plan_digest"]
        assert record.provenance["wireframe_digest"]
        assert record.provenance["validation"]["visual_design_checks"]["contrast_pairs"]
        assert db.query(AuditEvent).filter_by(
            project_id=uuid.UUID(project_id), event_type="operation.applied",
        ).count() >= 1
    finally:
        generator.close()


def test_apply_without_approval_is_rejected_without_authoritative_mutation(client):
    runtime, _ = _runtime()
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    project_id = _approved_sources(client)
    before = client.get(f"/api/v1/projects/{project_id}/design").json()
    _, operation = _propose_visual(client, project_id)
    response = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/apply")
    assert response.status_code == 409
    after = client.get(f"/api/v1/projects/{project_id}/design").json()
    assert after["state"] == before["state"]
    assert after["current_version_id"] == before["current_version_id"]
    assert client.get(f"/api/v1/projects/{project_id}/visual-design").status_code == 404


def test_failure_after_artifact_transition_rolls_back_authoritative_state(client, monkeypatch):
    runtime, _ = _runtime()
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    project_id = _approved_sources(client)
    before = client.get(f"/api/v1/projects/{project_id}/design").json()
    _, operation = _propose_visual(client, project_id)
    preview = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/preview").json()
    approved = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/approve", json={
        "preview_id": preview["id"], "approved": True,
    })
    assert approved.status_code == 200, approved.text

    def fail_during_state_write(*args, **kwargs):
        raise HTTPException(500, "Injected failure after artifact status transition")

    monkeypatch.setattr("app.services.operation_executor.update_design_state", fail_during_state_write)
    response = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/apply")
    assert response.status_code == 500
    after = client.get(f"/api/v1/projects/{project_id}/design").json()
    assert after["state"] == before["state"]
    assert after["current_version_id"] == before["current_version_id"]
    assert client.get(f"/api/v1/projects/{project_id}/visual-design").status_code == 404


def test_visual_schema_is_strict_and_deterministic_engine_preserves_wireframe_regions():
    schema = VisualDesignOutput.model_config
    assert schema["extra"] == "forbid" and schema["strict"] is True
    with pytest.raises(ValidationError):
        VisualDesignOutput.model_validate({"pages": [], "unexpected": True}, strict=True)
    approved_plan = {"pages": [{"id": "home"}]}
    wireframe = {"pages": [{"page_id": "home", "regions": [
        {"id": "hero", "name": "Hero", "component_refs": ["button"]},
    ]}]}
    output = DeterministicVisualDesignEngine().generate(approved_plan, wireframe)
    assert [page["page_id"] for page in output["pages"]] == ["home"]
    assert [region["region_id"] for region in output["pages"][0]["regions"]] == ["hero"]
    assert output["components"][0]["component_ref"] == "button"


def test_visual_candidate_stales_when_wireframe_content_changes(client):
    runtime, _ = _runtime()
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    project_id = _approved_sources(client)
    candidate, _ = _propose_visual(client, project_id)
    from app.core.database import get_db as db_dependency
    generator = app.dependency_overrides[db_dependency]()
    db = next(generator)
    try:
        row = db.query(VisualDesign).filter_by(candidate_id=uuid.UUID(candidate["candidate_id"])).one()
        from app.models.wireframe import WireframeSet
        wireframe = db.get(WireframeSet, row.wireframe_set_id)
        wireframe.wireframe = {**wireframe.wireframe, "rationale": "edited under the same ID"}
        db.commit()
    finally:
        generator.close()
    response = client.post(
        f"/api/v1/projects/{project_id}/visual-design/candidates/{candidate['candidate_id']}/operation"
    )
    assert response.status_code == 409
    assert "changed" in response.json()["detail"].lower()


def test_visual_candidate_stales_when_design_law_content_changes(client):
    runtime, _ = _runtime()
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    project_id = _approved_sources(client)
    candidate, operation = _propose_visual(client, project_id)
    law = client.get(f"/api/v1/projects/{project_id}/laws").json()[0]
    changed = client.patch(f"/api/v1/projects/{project_id}/laws/{law['id']}", json={
        "rule": "All primary actions remain keyboard accessible and visible.",
    })
    assert changed.status_code == 200, changed.text
    response = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/preview")
    assert response.status_code == 409
    assert client.get(f"/api/v1/projects/{project_id}/visual-design").status_code == 404
    assert client.get(f"/api/v1/projects/{project_id}/design").json()["state"]["visual_design"] == {}


@pytest.mark.parametrize("source", ["intent", "direction", "requirement"])
def test_visual_candidate_stales_when_reasoning_source_content_changes(client, source):
    runtime, _ = _runtime()
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    project_id = _approved_sources(client)
    _, operation = _propose_visual(client, project_id)
    from app.core.database import get_db as db_dependency
    from app.models.intent import ProjectIntent
    from app.models.direction import DesignDirection
    from app.models.requirement import DesignRequirement
    generator = app.dependency_overrides[db_dependency]()
    db = next(generator)
    try:
        if source == "intent":
            from app.models.project import Project
            project = db.get(Project, uuid.UUID(project_id))
            row = db.get(ProjectIntent, project.current_intent_id)
            row.business_or_product_goal += " Updated"
        elif source == "direction":
            from app.models.direction import DirectionStatus
            row = db.query(DesignDirection).filter_by(project_id=uuid.UUID(project_id), status=DirectionStatus.SELECTED).first()
            row.description += " Updated"
        else:
            row = db.query(DesignRequirement).filter_by(project_id=uuid.UUID(project_id)).first()
            assert row is not None
            row.requirement += " Updated"
        db.commit()
    finally:
        generator.close()
    response = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/preview")
    assert response.status_code == 409
    assert client.get(f"/api/v1/projects/{project_id}/visual-design").status_code == 404
    assert client.get(f"/api/v1/projects/{project_id}/design").json()["state"]["visual_design"] == {}


def test_schema_malformed_visual_output_is_quarantined_and_cannot_create_operation(client):
    runtime, _ = _runtime()
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    project_id = _approved_sources(client)
    malformed_provider = FakeModelProvider(responses={
        TaskType.VISUAL_DESIGN_GENERATION: [ProviderResult({"pages": [], "extra": "rejected"})],
    })
    runtime, _ = _runtime(malformed_provider)
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    candidate = client.post(f"/api/v1/projects/{project_id}/visual-design/propose")
    assert candidate.status_code == 200
    assert candidate.json()["accepted"] is False
    assert candidate.json()["candidate_id"] is not None
    operation = client.post(
        f"/api/v1/projects/{project_id}/visual-design/candidates/{candidate.json()['candidate_id']}/operation"
    )
    assert operation.status_code == 404


def test_visual_validator_rejects_unmapped_or_reordered_wireframe_structure():
    from types import SimpleNamespace
    plan = SimpleNamespace(plan={"pages": [{"id": "home"}]})
    wireframe = SimpleNamespace(wireframe={"pages": [{"page_id": "home", "regions": [
        {"id": "hero", "name": "Hero", "component_refs": ["button"]},
    ]}]})
    output = DeterministicVisualDesignEngine().generate(plan.plan, wireframe.wireframe)
    output["pages"][0]["regions"].append({**output["pages"][0]["regions"][0], "region_id": "invented"})
    with pytest.raises(HTTPException) as exc:
        VisualDesignWorkflow.validate_semantics(plan, wireframe, output)
    assert exc.value.status_code == 422


def test_visual_validator_rejects_undefined_token_references():
    from types import SimpleNamespace
    plan = SimpleNamespace(plan={"pages": [{"id": "home"}]})
    wireframe = SimpleNamespace(wireframe={"pages": [{"page_id": "home", "regions": [
        {"id": "hero", "name": "Hero", "component_refs": ["button"]},
    ]}]})
    output = DeterministicVisualDesignEngine().generate(plan.plan, wireframe.wireframe)
    output["pages"][0]["regions"][0]["token_refs"].append("missing.token")
    with pytest.raises(HTTPException, match="undefined token") as exc:
        VisualDesignWorkflow.validate_semantics(plan, wireframe, output)
    assert exc.value.status_code == 422


def test_visual_validator_rejects_failing_declared_contrast_pairs():
    from types import SimpleNamespace
    plan = SimpleNamespace(plan={"pages": [{"id": "home"}]})
    wireframe = SimpleNamespace(wireframe={"pages": [{"page_id": "home", "regions": [
        {"id": "hero", "name": "Hero", "component_refs": ["button"]},
    ]}]})
    output = DeterministicVisualDesignEngine().generate(plan.plan, wireframe.wireframe)
    output["colors"]["primary"]["value"] = "#FFFFFF"
    with pytest.raises(HTTPException, match="contrast pairs fail") as exc:
        VisualDesignWorkflow.validate_semantics(plan, wireframe, output)
    assert exc.value.status_code == 422


def test_ai_actor_cannot_approve_or_apply_visual_design_operation(client):
    runtime, _ = _runtime()
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    project_id = _approved_sources(client)
    _, operation = _propose_visual(client, project_id)
    preview = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/preview").json()
    app.dependency_overrides[get_actor_context] = lambda: ActorContext(ActorType.AI, actor_id="ai", trusted=True)
    approve = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/approve", json={
        "preview_id": preview["id"], "approved": True,
    })
    assert approve.status_code == 403
    apply = client.post(f"/api/v1/projects/{project_id}/operations/{operation['id']}/apply")
    assert apply.status_code == 403


def test_restoring_prior_visual_version_reactivates_its_artifact(client):
    runtime, _ = _runtime()
    app.dependency_overrides[get_provider_runtime] = lambda: runtime
    project_id = _approved_sources(client)
    _, first_operation = _propose_visual(client, project_id)
    _approve_and_apply(client, project_id, first_operation["id"])
    first = client.get(f"/api/v1/projects/{project_id}/visual-design").json()
    first_version = client.get(f"/api/v1/projects/{project_id}/design").json()["current_version_id"]
    _, second_operation = _propose_visual(client, project_id)
    _approve_and_apply(client, project_id, second_operation["id"])
    second = client.get(f"/api/v1/projects/{project_id}/visual-design").json()
    assert second["id"] != first["id"]
    restored = client.post(f"/api/v1/projects/{project_id}/versions/{first_version}/restore")
    assert restored.status_code == 200, restored.text
    current = client.get(f"/api/v1/projects/{project_id}/visual-design")
    assert current.status_code == 200
    assert current.json()["id"] == first["id"]


def test_build06_migration_lineage_and_constraints():
    assert migration.revision == "0006_visual_design_intelligence"
    assert migration.down_revision == "0005_wireframe_intelligence"
    assert migration.VISUAL_DESIGN_STATUSES == ("proposed", "previewed", "approved", "rejected", "superseded")
    from app.models.visual_design import VisualDesign
    constraints = {item.name for item in VisualDesign.__table__.constraints}
    assert {
        "fk_visual_designs_plan_project", "fk_visual_designs_wireframe_project",
        "fk_visual_designs_intent_revision", "fk_visual_designs_direction_project",
        "uq_visual_design_candidate",
    } <= constraints
