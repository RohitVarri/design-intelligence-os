"""Deterministic wireframe fixtures and proposal workflow."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actors import ActorContext, ActorType
from app.core.locking import lock_project
from app.models.ai_candidate import AIOutputCandidate
from app.models.ai_run import AIRun, AIRunStatus
from app.models.design_plan import DesignPlan, DesignPlanStatus
from app.models.design_state import DesignState
from app.models.direction import DesignDirection, DirectionStatus
from app.models.project import Project
from app.models.wireframe import WireframeSet
from app.providers.contracts import TaskType
from app.providers.runtime import ProviderRuntime
from app.schemas.operation import OperationCreate
from app.schemas.wireframe import WireframeOutput, WireframeSetStatus
from app.services.design_reasoning import DesignReasoningService
from app.services.operation_executor import OperationExecutor


def stable_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class DeterministicWireframeEngine:
    """Produce a transparent structural baseline for offline use and tests."""

    def generate(self, approved_plan: dict[str, Any]) -> dict[str, Any]:
        pages = []
        shared = approved_plan.get("component_strategy", {}).get("shared_components", [])
        page_components = approved_plan.get("component_strategy", {}).get("page_specific_components", {})
        for page in approved_plan.get("pages", []):
            sections = page.get("sections") or ["Primary content", "Supporting content"]
            refs = list(dict.fromkeys([*shared, *page_components.get(page.get("name"), [])]))
            regions = [
                {
                    "id": f"{page['id']}-region-{index}",
                    "name": section,
                    "purpose": section,
                    "hierarchy_order": index,
                    "content_elements": [section],
                    "component_refs": refs,
                    "interactions": [page.get("primary_action", "Continue") ] if index == 1 else [],
                }
                for index, section in enumerate(sections, start=1)
            ]
            pages.append({
                "page_id": page["id"],
                "layout_summary": page.get("purpose", page.get("name", "Page")),
                "regions": regions,
                "responsive_notes": page.get("responsive_notes", []),
                "accessibility_notes": page.get("accessibility_notes", []),
                "rationale": page.get("rationale", "Derived from the approved page plan."),
            })
        return {"pages": pages, "rationale": "Structural wireframe derived from the approved Design Plan.", "confidence": 0.65}


class WireframeWorkflow:
    """Generate, validate, persist, and operation-bind wireframe candidates."""

    def __init__(self, reasoning: DesignReasoningService | None = None):
        self.reasoning = reasoning or DesignReasoningService()

    def _current_plan(self, db: Session, project_id: uuid.UUID) -> tuple[Project, DesignPlan, dict]:
        project = db.get(Project, project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
        state = db.get(DesignState, project_id)
        record_id = ((state.state or {}).get("design_plan") or {}).get("record_id") if state else None
        try:
            plan_id = uuid.UUID(str(record_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(409, "An approved Design Plan is required before wireframe generation") from exc
        plan = db.scalar(select(DesignPlan).where(
            DesignPlan.id == plan_id,
            DesignPlan.project_id == project_id,
            DesignPlan.status == DesignPlanStatus.APPROVED,
        ))
        context = self.reasoning.build_context(db, project_id)
        if plan is None or str(plan.intent_id) != context["intent_revision_id"] or str(plan.direction_id) != context["direction_id"]:
            raise HTTPException(409, "The approved Design Plan is stale for the current intent or direction")
        return project, plan, context

    @staticmethod
    def _validate_semantics(plan: DesignPlan, output: dict[str, Any]) -> None:
        expected = [str(page.get("id")) for page in plan.plan.get("pages", [])]
        received = [str(page.get("page_id")) for page in output.get("pages", [])]
        if not expected or len(received) != len(set(received)) or set(received) != set(expected):
            raise HTTPException(422, "Wireframe pages must cover each approved plan page exactly once")
        for page in output["pages"]:
            regions = page.get("regions", [])
            region_ids = [region.get("id") for region in regions]
            order = [region.get("hierarchy_order") for region in regions]
            if len(region_ids) != len(set(region_ids)) or len(order) != len(set(order)):
                raise HTTPException(422, "Wireframe region IDs and hierarchy positions must be unique per page")

    def propose(self, db: Session, project_id: uuid.UUID, runtime: ProviderRuntime) -> dict[str, Any]:
        _, plan, context = self._current_plan(db, project_id)
        plan_digest = stable_digest(plan.plan)
        refs = {
            "design_plan_id": str(plan.id),
            "design_plan_digest": plan_digest,
            "source_context_digest": context["source_manifest"]["content_digest"],
            "source_manifest": context["source_manifest"],
        }
        result = runtime.execute_sync(
            db,
            project_id=project_id,
            intent_id=plan.intent_id,
            task=TaskType.WIREFRAME_GENERATION,
            payload={"approved_plan": plan.plan, "reasoning_context": context},
            output_schema=WireframeOutput,
            actor=ActorContext(ActorType.AI, actor_id="wireframe-runtime", trusted=True),
            context_references=refs,
        )
        candidate = result.candidate
        if result.accepted and candidate is not None:
            wireframe = WireframeOutput.model_validate(candidate.payload, strict=True).model_dump(mode="json")
            try:
                self._validate_semantics(plan, wireframe)
            except HTTPException as exc:
                candidate.validation_status = "quarantined"
                candidate.validation_error = "Wireframe semantic validation failed"
                run = result.run
                run.status = AIRunStatus.MALFORMED
                run.error = "wireframe semantic validation failed"
                run.completed_at = datetime.now(timezone.utc)
                db.flush()
                return {"run_id": run.id, "candidate_id": candidate.id, "status": run.status.value,
                        "candidate": None, "accepted": False}
            record = WireframeSet(
                project_id=project_id,
                design_plan_id=plan.id,
                intent_id=plan.intent_id,
                direction_id=plan.direction_id,
                candidate_id=candidate.id,
                status=WireframeSetStatus.PROPOSED,
                wireframe=wireframe,
                provenance={"source_type": "ai_wireframe_intelligence", **refs, "ai_run_id": str(result.run.id), "candidate_id": str(candidate.id)},
            )
            db.add(record)
            db.flush()
        return {"run_id": result.run.id, "candidate_id": candidate.id if candidate else None,
                "status": result.run.status.value, "candidate": candidate.payload if candidate else None,
                "accepted": result.accepted}

    def create_operation(self, db: Session, project_id: uuid.UUID, candidate_id: uuid.UUID,
                         actor: ActorContext, executor: OperationExecutor):
        lock_project(db, project_id)
        _, plan, context = self._current_plan(db, project_id)
        candidate = db.scalar(select(AIOutputCandidate).where(
            AIOutputCandidate.id == candidate_id,
            AIOutputCandidate.project_id == project_id,
            AIOutputCandidate.candidate_type == TaskType.WIREFRAME_GENERATION.value,
            AIOutputCandidate.validation_status == "valid",
        ))
        record = db.scalar(select(WireframeSet).where(WireframeSet.candidate_id == candidate_id, WireframeSet.project_id == project_id))
        run = db.get(AIRun, candidate.run_id) if candidate else None
        if not candidate or not record or not run or run.status.value != "succeeded":
            raise HTTPException(404, "Validated wireframe candidate not found")
        if record.design_plan_id != plan.id or record.status != WireframeSetStatus.PROPOSED:
            raise HTTPException(409, "Wireframe candidate is stale or no longer eligible")
        if record.provenance.get("source_context_digest") != context["source_manifest"]["content_digest"]:
            raise HTTPException(409, "Wireframe reasoning context changed; generate a new candidate")
        if record.provenance.get("design_plan_digest") != stable_digest(plan.plan):
            raise HTTPException(409, "Approved Design Plan content changed; generate a new wireframe candidate")
        value = {"wireframe": record.wireframe, "design_plan_id": str(plan.id),
                 "intent_revision_id": str(plan.intent_id), "direction_id": str(plan.direction_id),
                 "wireframe_set_id": str(record.id)}
        provenance = dict(record.provenance)
        data = OperationCreate(
            operation_type="create", actor="ai", target="metadata.wireframes", property="metadata.wireframes",
            new_value=value, reason=f"Propose wireframes from approved Design Plan {plan.id}.",
            source="ai_proposal", intent_id=plan.intent_id, ai_run_id=run.id, candidate_id=candidate.id,
            direction_id=plan.direction_id, provenance=provenance,
        )
        return executor.propose(db, project_id, data, ActorContext(ActorType.AI, actor_id="wireframe-runtime", trusted=True))


def read_approved_wireframes(db: Session, project_id: uuid.UUID) -> WireframeSet:
    state = db.get(DesignState, project_id)
    raw_id = ((state.state or {}).get("wireframes") or {}).get("record_id") if state else None
    try:
        wireframe_id = uuid.UUID(str(raw_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(404, "Approved wireframes not found") from exc
    row = db.scalar(select(WireframeSet).where(
        WireframeSet.id == wireframe_id, WireframeSet.project_id == project_id,
        WireframeSet.status == WireframeSetStatus.APPROVED,
    ))
    if row is None:
        raise HTTPException(404, "Approved wireframes not found")
    return row
