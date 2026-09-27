"""Provider-backed plan candidates and conversion into the shared operation boundary."""
import uuid
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actors import ActorContext, ActorType
from app.models.ai_candidate import AIOutputCandidate
from app.models.ai_run import AIRun
from app.models.design_plan import DesignPlan
from app.models.intent import ProjectIntent
from app.models.project import Project
from app.providers.contracts import TaskType
from app.providers.runtime import ProviderRuntime
from app.schemas.design_plan import DesignPlanOutput, DesignPlanStatus
from app.schemas.operation import OperationCreate
from app.services.design_reasoning import DesignReasoningService
from app.services.operation_executor import OperationExecutor


class DesignPlanWorkflow:
    """Orchestrate a proposal-only plan candidate and an explicit executor-backed operation."""

    def __init__(self, reasoning: DesignReasoningService | None = None):
        self.reasoning = reasoning or DesignReasoningService()

    def propose(
        self,
        db: Session,
        project_id: uuid.UUID,
        runtime: ProviderRuntime,
    ) -> dict[str, Any]:
        context = self.reasoning.build_context(db, project_id)
        ai_actor = ActorContext(ActorType.AI, actor_id="design-reasoning-runtime", trusted=True)
        result = runtime.execute_sync(
            db,
            project_id=project_id,
            intent_id=uuid.UUID(context["intent_revision_id"]),
            task=TaskType.DESIGN_PLAN_GENERATION,
            payload={"reasoning_context": context},
            output_schema=DesignPlanOutput,
            actor=ai_actor,
            context_references={"source_manifest": context["source_manifest"], "direction_id": context["direction_id"]},
        )
        candidate = result.candidate
        if result.accepted and candidate is not None:
            plan = DesignPlanOutput.model_validate_json(json.dumps(candidate.payload), strict=True)
            provenance = self._provenance(context, result.run.id, candidate.id)
            row = DesignPlan(
                project_id=project_id,
                intent_id=uuid.UUID(context["intent_revision_id"]),
                direction_id=uuid.UUID(context["direction_id"]),
                candidate_id=candidate.id,
                status=DesignPlanStatus.PROPOSED,
                plan=plan.model_dump(mode="json"),
                confidence=plan.confidence,
                provenance=provenance,
            )
            db.add(row)
            db.flush()
        return {
            "run_id": result.run.id,
            "candidate_id": candidate.id if candidate else None,
            "status": result.run.status.value,
            "candidate": candidate.payload if candidate else None,
            "accepted": result.accepted,
        }

    def create_operation(
        self,
        db: Session,
        project_id: uuid.UUID,
        candidate_id: uuid.UUID,
        actor: ActorContext,
        executor: OperationExecutor,
    ):
        project = db.get(Project, project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
        candidate = db.scalar(
            select(AIOutputCandidate).where(
                AIOutputCandidate.id == candidate_id,
                AIOutputCandidate.project_id == project_id,
                AIOutputCandidate.candidate_type == TaskType.DESIGN_PLAN_GENERATION.value,
                AIOutputCandidate.validation_status == "valid",
            )
        )
        if candidate is None:
            raise HTTPException(404, "Validated Design Plan candidate not found")
        row = db.scalar(select(DesignPlan).where(DesignPlan.candidate_id == candidate.id, DesignPlan.project_id == project_id))
        run = db.get(AIRun, candidate.run_id)
        if row is None or run is None or run.status.value != "succeeded":
            raise HTTPException(409, "Candidate does not have a successful Design Plan run")
        context = self.reasoning.build_context(db, project_id)
        if str(row.intent_id) != context["intent_revision_id"]:
            raise HTTPException(409, "Design Plan candidate uses a stale intent revision")
        if str(row.direction_id) != context["direction_id"]:
            raise HTTPException(409, "Design Plan candidate uses a stale selected direction")
        source_manifest = row.provenance["source_manifest"]
        now = datetime.now(timezone.utc).isoformat()
        value = {
            "plan": row.plan,
            "intent_revision_id": str(row.intent_id),
            "direction_id": str(row.direction_id),
            "provenance": row.provenance,
        }
        operation = OperationCreate(
            operation_type="create",
            actor="ai",
            target="metadata.design_plan",
            property="metadata.design_plan",
            new_value=value,
            reason=f"Propose a structured Design Plan for the selected direction based on intent revision {row.intent_id}.",
            source="ai_proposal",
            intent_id=row.intent_id,
            ai_run_id=run.id,
            candidate_id=candidate.id,
            direction_id=row.direction_id,
            provenance={
                **row.provenance,
                "source_manifest": source_manifest,
                "research_ids": source_manifest["research"],
                "requirement_ids": source_manifest["requirements"],
                "created_at": now,
            },
        )
        return executor.propose(db, project_id, operation, ActorContext(ActorType.AI, actor_id="design-reasoning-runtime", trusted=True))

    @staticmethod
    def _provenance(context: dict, run_id: uuid.UUID, candidate_id: uuid.UUID) -> dict:
        manifest = context["source_manifest"]
        return {
            "source_type": "ai_design_reasoning",
            "intent_revision_id": context["intent_revision_id"],
            "direction_id": context["direction_id"],
            "ai_run_id": str(run_id),
            "candidate_id": str(candidate_id),
            "requirement_ids": manifest["requirements"],
            "research_ids": manifest["research"],
            "design_law_ids": manifest["design_laws"],
            "question_ids": manifest["questions"],
            "source_manifest": manifest,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "engine": "build04_design_reasoning",
        }
