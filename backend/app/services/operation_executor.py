"""Authorized, previewable, atomic application path for design mutations."""
import copy
import hashlib
import json
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.actors import ActorContext, ActorType, AuthorizationPolicy
from app.models.ai_run import AIRun
from app.models.decision import DecisionSource, DesignDecision
from app.models.direction import DesignDirection, DirectionStatus
from app.models.intent import IntentStatus, ProjectIntent
from app.models.memory import DesignMemory, MemoryTrust
from app.models.operation import DesignOperation, OperationActor, OperationSource, OperationStatus, OperationType
from app.models.operation_records import AuditEvent, OperationApproval, OperationPreview
from app.models.project import Project
from app.models.research_evidence import EvidenceTrust, ResearchEvidence
from app.models.design_state import DesignState
from app.models.version import DesignVersion
from app.schemas.operation import OperationCreate
from app.schemas.design import DesignStateInput
from app.services.design_state import DEFAULT_STATE, create_initial_design_state, update_design_state
from app.services.intent import IntentExtractionService


class OperationExecutor:
    def __init__(self, authorization: AuthorizationPolicy | None = None):
        self.authorization = authorization or AuthorizationPolicy()

    @staticmethod
    def _actor(actor: ActorContext) -> OperationActor:
        return OperationActor(actor.actor_type.value)

    @staticmethod
    def _source(actor: ActorContext) -> OperationSource:
        if actor.actor_type == ActorType.AI: return OperationSource.AI_PROPOSAL
        if actor.actor_type == ActorType.SYSTEM: return OperationSource.SYSTEM
        return OperationSource.USER_REQUEST

    def propose(self, db: Session, project_id: uuid.UUID, data: OperationCreate, actor: ActorContext) -> DesignOperation:
        self.authorization.require(actor, "propose")
        if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
        project = db.get(Project, project_id)
        intent_id = data.intent_id or project.current_intent_id
        if intent_id and not db.scalar(select(ProjectIntent.id).where(ProjectIntent.project_id == project_id, ProjectIntent.id == intent_id)):
            raise HTTPException(422, "Intent revision does not belong to this project")
        if data.ai_run_id:
            run = db.get(AIRun, data.ai_run_id)
            if not run or run.project_id != project_id: raise HTTPException(422, "AI Run does not belong to this project")
            if actor.actor_type != ActorType.AI: raise HTTPException(422, "Only an AI actor can attach an AI Run")
        values = data.model_dump(exclude={"actor", "source", "status"})
        operation = DesignOperation(project_id=project_id, actor=self._actor(actor), source=self._source(actor), status=OperationStatus.PROPOSED, **values)
        operation.provenance = {**(data.provenance or {}), "actor_type":actor.actor_type.value if actor.actor_type else None, "actor_id":actor.actor_id,
                                "intent_revision_id":str(intent_id) if intent_id else None, "created_at":datetime.now(timezone.utc).isoformat()}
        operation.intent_id = intent_id
        db.add(operation); db.flush()
        self._event(db, operation, actor, "operation.proposed", "Operation proposal recorded")
        return operation

    def reject(self, db: Session, operation: DesignOperation, actor: ActorContext, reason: str) -> None:
        """Persist a fail-closed validation rejection and its explanation."""
        operation.status = OperationStatus.REJECTED
        operation.provenance = {**(operation.provenance or {}), "rejection": {"reason": reason, "rejected_at": datetime.now(timezone.utc).isoformat()}}
        self._event(db, operation, actor, "operation.rejected", "Operation rejected during validation", {"reason": reason})
        db.flush()

    def validate(self, db: Session, operation: DesignOperation) -> dict:
        project = db.scalar(select(Project).where(Project.id == operation.project_id).with_for_update())
        if not project: raise HTTPException(404, "Project not found")
        issues: list[str] = []
        if operation.intent_id and project.current_intent_id != operation.intent_id:
            issues.append("Operation is based on a stale intent revision")
        if operation.actor == OperationActor.AI:
            if operation.source != OperationSource.AI_PROPOSAL or not operation.ai_run_id:
                issues.append("AI proposal requires AI Run provenance")
            else:
                run = db.get(AIRun, operation.ai_run_id)
                if not run or run.project_id != operation.project_id:
                    issues.append("AI proposal references an unavailable AI Run")
                elif run.status.value != "succeeded":
                    issues.append("AI proposal requires a successfully validated AI Run")
                elif run.intent_id != operation.intent_id or run.intent_id != project.current_intent_id:
                    issues.append("AI proposal is based on a stale intent revision")
            refs = (operation.provenance or {}).get("research_ids", [])
            if refs:
                try:
                    evidence_ids = [uuid.UUID(str(value)) for value in refs]
                except (ValueError, TypeError, AttributeError) as exc:
                    raise HTTPException(422, "Proposal contains an invalid research evidence reference") from exc
                rows = db.scalars(select(ResearchEvidence).where(ResearchEvidence.id.in_(evidence_ids), ResearchEvidence.project_id == operation.project_id)).all()
                by_id = {str(row.id): row for row in rows}
                if len(by_id) != len(set(map(str, refs))): issues.append("Proposal references unavailable research evidence")
                for row in by_id.values():
                    if row.trust == EvidenceTrust.UNTRUSTED:
                        issues.append(f"Research evidence {row.id} is untrusted")
                    if row.intent_id != operation.intent_id or row.intent_id != project.current_intent_id:
                        issues.append(f"Research evidence {row.id} is based on a stale intent revision")
        if issues:
            raise HTTPException(409, "; ".join(dict.fromkeys(issues)))
        target = operation.property or operation.target
        root = target.split(".", 1)[0]
        if operation.operation_type in {OperationType.MOVE, OperationType.REORDER, OperationType.UPDATE_REQUIREMENT, OperationType.UPDATE_INTENT}:
            raise HTTPException(422, f"Operation type '{operation.operation_type.value}' is not supported by the BUILD 03 executor")
        allowed = {"pages", "components", "design_tokens", "ux_navigation", "assets", "metadata", "direction_selection"}
        if operation.operation_type == OperationType.SELECT_DIRECTION:
            direction_id = self._direction_id(operation)
            direction = db.scalar(select(DesignDirection).where(DesignDirection.project_id == operation.project_id, DesignDirection.id == direction_id))
            if not direction or direction.intent_id != project.current_intent_id:
                raise HTTPException(409, "Direction is stale or unavailable")
            if direction.status != DirectionStatus.PROPOSED:
                raise HTTPException(409, "Only proposed directions can be selected")
        elif not (operation.operation_type == OperationType.REPLACE and target == "*") and (root not in allowed or root == "direction_selection"):
            raise HTTPException(422, "Operation target is outside the editable design-state surface")
        if root == "design_laws": raise HTTPException(403, "Operations cannot create or modify approved design laws")
        if operation.operation_type == OperationType.REPLACE and target == "*":
            current_state = db.get(DesignState, operation.project_id)
            before_laws = (current_state.state if current_state else DEFAULT_STATE).get("design_laws", [])
            after_laws = (operation.new_value or {}).get("design_laws", []) if isinstance(operation.new_value, dict) else None
            if after_laws != before_laws:
                raise HTTPException(403, "Design laws must be changed through the dedicated user-authorized law workflow")
        return {"valid":True, "intent_revision_id":str(operation.intent_id) if operation.intent_id else None, "target":target}

    @staticmethod
    def _direction_id(operation: DesignOperation) -> uuid.UUID:
        raw = operation.target.removeprefix("design_direction:")
        try: return uuid.UUID(raw)
        except ValueError as exc: raise HTTPException(422, "Invalid direction target") from exc

    def preview(self, db: Session, operation_id: uuid.UUID, actor: ActorContext) -> OperationPreview:
        self.authorization.require(actor, "preview")
        operation = db.get(DesignOperation, operation_id)
        if not operation: raise HTTPException(404, "Operation not found")
        if operation.status not in {OperationStatus.PROPOSED, OperationStatus.VALIDATED, OperationStatus.PREVIEWED}:
            raise HTTPException(409, "Operation is not eligible for preview")
        validation = self.validate(db, operation)
        current = db.get(DesignState, operation.project_id)
        before = copy.deepcopy(current.state if current else DEFAULT_STATE)
        after = copy.deepcopy(before)
        if operation.operation_type == OperationType.SELECT_DIRECTION:
            direction_id = self._direction_id(operation)
            direction = db.get(DesignDirection, direction_id)
            after.setdefault("metadata", {})["selected_direction"] = {"id":str(direction.id), "name":direction.name, "intent_revision_id":str(direction.intent_id)}
            after["direction_selection"] = {"direction_id": str(direction.id), "direction_name": direction.name}
        elif operation.operation_type == OperationType.REPLACE and (operation.property or operation.target) == "*":
            if not isinstance(operation.new_value, dict): raise HTTPException(422, "Full-state replacement requires an object")
            after = copy.deepcopy(operation.new_value)
        else:
            self._apply_to_copy(after, operation)
        try:
            if not set(DEFAULT_STATE).issubset(after):
                raise ValueError("required top-level state sections are missing")
            after = DesignStateInput.model_validate(after).model_dump(mode="json")
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, f"Operation would produce an invalid Design State: {exc}") from exc
        base = current.current_version_id if current else None
        digest = _digest(before)
        preview = OperationPreview(operation_id=operation.id, base_version_id=base, before_state=before, after_state=after,
            impact={"changed_paths":_diff_paths(before, after), "scope":operation.scope, "risks":[], "requires_user_approval":True},
            provenance={"validation":validation, "source":operation.source.value, "intent_revision_id":str(operation.intent_id) if operation.intent_id else None}, state_digest=digest)
        db.add(preview); operation.status=OperationStatus.PREVIEWED
        self._event(db, operation, actor, "operation.previewed", "Non-mutating operation preview generated", {"preview_id":str(preview.id),"digest":digest})
        db.flush()
        return preview

    def approve(self, db: Session, operation_id: uuid.UUID, preview_id: uuid.UUID, actor: ActorContext, approved: bool = True) -> OperationApproval:
        self.authorization.require(actor, "approve")
        operation = db.get(DesignOperation, operation_id)
        preview = db.scalar(select(OperationPreview).where(OperationPreview.id == preview_id, OperationPreview.operation_id == operation_id))
        if not operation or not preview: raise HTTPException(404, "Operation or preview not found")
        if operation.status != OperationStatus.PREVIEWED: raise HTTPException(409, "Operation must have a current preview before approval")
        current = db.get(DesignState, operation.project_id)
        current_state = current.state if current else DEFAULT_STATE
        if (current.current_version_id if current else None) != preview.base_version_id or _digest(current_state) != preview.state_digest:
            raise HTTPException(409, "Design State changed after preview; generate a new preview")
        approval = OperationApproval(operation_id=operation.id, preview_id=preview.id, actor_type=actor.actor_type.value,
                                     actor_id=actor.actor_id or "trusted-user", approved=approved)
        db.add(approval)
        operation.status = OperationStatus.APPROVED if approved else OperationStatus.REJECTED
        self._event(db, operation, actor, "operation.approved" if approved else "operation.rejected", "User approval recorded" if approved else "User rejected operation", {"preview_id":str(preview.id)})
        db.flush(); return approval

    def apply(self, db: Session, operation_id: uuid.UUID, actor: ActorContext) -> DesignOperation:
        """Apply in a savepoint so a partial failure cannot leak design/version writes."""
        with db.begin_nested():
            return self._apply_in_transaction(db, operation_id, actor)

    def _apply_in_transaction(self, db: Session, operation_id: uuid.UUID, actor: ActorContext) -> DesignOperation:
        self.authorization.require(actor, "apply")
        operation = db.get(DesignOperation, operation_id)
        if not operation: raise HTTPException(404, "Operation not found")
        if operation.status == OperationStatus.APPLIED: return operation
        if operation.status != OperationStatus.APPROVED: raise HTTPException(409, "Operation requires explicit approval")
        approval = db.scalar(select(OperationApproval).where(OperationApproval.operation_id == operation_id, OperationApproval.approved.is_(True)))
        if not approval: raise HTTPException(409, "No approved preview is recorded")
        preview = db.get(OperationPreview, approval.preview_id)
        validation = self.validate(db, operation)
        current = db.get(DesignState, operation.project_id)
        current_state = current.state if current else DEFAULT_STATE
        if (current.current_version_id if current else None) != preview.base_version_id or _digest(current_state) != preview.state_digest:
            raise HTTPException(409, "Design State changed after approval; operation cannot be applied")
        next_state = copy.deepcopy(preview.after_state)
        if not current: current = create_initial_design_state(db, operation.project_id)
        updated = update_design_state(db, operation.project_id, next_state, operation.reason)
        operation.status = OperationStatus.APPLIED
        operation.provenance = {**(operation.provenance or {}), "applied_version_id":str(updated.current_version_id), "applied_at":datetime.now(timezone.utc).isoformat(), "validation":validation}
        if operation.operation_type == OperationType.SELECT_DIRECTION:
            self._apply_direction_selection(db, operation, actor)
        self._event(db, operation, actor, "operation.applied", "Operation applied atomically", {"version_id":str(updated.current_version_id)})
        candidate = (operation.provenance or {}).get("memory_candidate", {})
        content = candidate.get("content") or f"Applied {operation.operation_type.value} at {operation.property or operation.target}: {operation.reason}"
        category = candidate.get("category", "design_change")
        memory = db.scalar(select(DesignMemory).where(DesignMemory.source_operation_id == operation.id))
        if memory is None:
            db.add(DesignMemory(project_id=operation.project_id, category=category, content=content, trust=MemoryTrust.USER_APPROVED,
                source_operation_id=operation.id, provenance={"operation_id":str(operation.id),"source_id":str(self._direction_id(operation)) if operation.operation_type == OperationType.SELECT_DIRECTION else str(operation.id),"actor_id":actor.actor_id,"actor_type":actor.actor_type.value,
                "intent_revision_id":str(operation.intent_id) if operation.intent_id else None,"created_version_id":str(updated.current_version_id),
                "source":operation.source.value,"ai_run_id":str(operation.ai_run_id) if operation.ai_run_id else None}))
        db.flush()
        return operation

    def execute_confirmed_user_request(self, db: Session, project_id: uuid.UUID, data: OperationCreate, actor: ActorContext) -> DesignOperation:
        """Compatibility path for explicit user updates; still traverses executor stages."""
        operation = self.propose(db, project_id, data, actor)
        preview = self.preview(db, operation.id, actor)
        self.approve(db, operation.id, preview.id, actor, True)
        return self.apply(db, operation.id, actor)

    def _apply_direction_selection(self, db: Session, operation: DesignOperation, actor: ActorContext) -> None:
        direction = db.get(DesignDirection, self._direction_id(operation))
        if not direction or direction.intent_id != operation.intent_id: raise HTTPException(409, "Direction became stale")
        old_selected = db.scalars(select(DesignDirection).where(DesignDirection.project_id == operation.project_id, DesignDirection.status == DirectionStatus.SELECTED)).all()
        for old in old_selected: old.status = DirectionStatus.ARCHIVED
        direction.status = DirectionStatus.SELECTED
        intent = db.get(ProjectIntent, operation.intent_id)
        IntentExtractionService.transition_status(intent, IntentStatus.APPROVED, actor=actor.actor_type.value, reason="User approved a design direction operation")
        db.add(DesignDecision(project_id=operation.project_id, source=DecisionSource.USER, title=f"Selected design direction: {direction.name}",
            rationale=f"The user explicitly approved '{direction.name}'. {direction.description}", provenance={"source_type":"user_selection","source_id":str(direction.id),"operation_id":str(operation.id),"actor_id":actor.actor_id,"intent_revision_id":str(intent.id)}))

    @staticmethod
    def _apply_to_copy(state: dict, operation: DesignOperation) -> None:
        if operation.operation_type == OperationType.REPLACE and (operation.property or operation.target) == "*":
            raise HTTPException(422, "Root replacement handled by executor")
        path = (operation.property or operation.target).split(".")
        node = state
        try:
            for token in path[:-1]: node = node[int(token)] if isinstance(node, list) else node[token]
            key = path[-1]
            exists = int(key) < len(node) if isinstance(node, list) and key.isdigit() else key in node
            if operation.operation_type == OperationType.CREATE and exists:
                raise HTTPException(409, "CREATE target already exists")
            if operation.operation_type in {OperationType.UPDATE, OperationType.DELETE, OperationType.REPLACE} and not exists:
                raise HTTPException(404, "Operation target does not exist")
            if operation.operation_type == OperationType.DELETE:
                if isinstance(node, list): del node[int(key)]
                else: del node[key]
            elif isinstance(node, list): node[int(key)] = operation.new_value
            else: node[key] = operation.new_value
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise HTTPException(422, f"Invalid operation target: {'.'.join(path)}") from exc

    @staticmethod
    def _event(db: Session, operation: DesignOperation, actor: ActorContext, event: str, reason: str, details: dict | None = None) -> None:
        db.add(AuditEvent(project_id=operation.project_id, operation_id=operation.id, actor_type=actor.actor_type.value if actor.actor_type else "anonymous",
            actor_id=actor.actor_id, event_type=event, reason=reason, details=details or {}))


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _diff_paths(before: dict, after: dict, prefix="") -> list[str]:
    paths=[]
    for key in sorted(set(before) | set(after)):
        path=f"{prefix}.{key}" if prefix else key
        if key not in before or key not in after: paths.append(path)
        elif isinstance(before[key],dict) and isinstance(after[key],dict): paths.extend(_diff_paths(before[key],after[key],path))
        elif before[key] != after[key]: paths.append(path)
    return paths
