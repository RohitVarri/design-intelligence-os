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
from app.core.locking import lock_project
from app.models.ai_run import AIRun
from app.models.ai_candidate import AIOutputCandidate
from app.models.design_plan import DesignPlan, DesignPlanStatus
from app.models.decision import DecisionSource, DesignDecision
from app.models.direction import DesignDirection, DirectionStatus
from app.models.intent import IntentStatus, ProjectIntent
from app.models.memory import DesignMemory, MemoryTrust
from app.models.operation import DesignOperation, OperationActor, OperationSource, OperationStatus, OperationType
from app.models.operation_records import AuditEvent, OperationApproval, OperationPreview
from app.models.project import Project
from app.models.research_evidence import EvidenceTrust, ResearchEvidence
from app.models.requirement import DesignRequirement, RequirementStatus
from app.models.design_law import DesignLaw
from app.models.question import Question, QuestionPriority, QuestionStatus
from app.models.design_state import DesignState
from app.models.version import DesignVersion
from app.models.wireframe import WireframeSet
from app.models.visual_design import VisualDesign
from app.schemas.wireframe import WireframeOutput, WireframeSetStatus
from app.schemas.visual_design import VisualDesignOutput, VisualDesignStatus
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
        if operation.candidate_id:
            wireframe_record = db.scalar(select(WireframeSet).where(WireframeSet.candidate_id == operation.candidate_id))
            if wireframe_record and wireframe_record.status in {WireframeSetStatus.PROPOSED, WireframeSetStatus.PREVIEWED}:
                wireframe_record.status = WireframeSetStatus.REJECTED
            visual_record = db.scalar(select(VisualDesign).where(VisualDesign.candidate_id == operation.candidate_id))
            if visual_record and visual_record.status in {VisualDesignStatus.PROPOSED, VisualDesignStatus.PREVIEWED}:
                visual_record.status = VisualDesignStatus.REJECTED
        self._event(db, operation, actor, "operation.rejected", "Operation rejected during validation", {"reason": reason})
        db.flush()

    def validate(self, db: Session, operation: DesignOperation) -> dict:
        project = lock_project(db, operation.project_id)
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
            before_state = current_state.state if current_state else DEFAULT_STATE
            before_laws = before_state.get("design_laws", [])
            after_laws = (operation.new_value or {}).get("design_laws", []) if isinstance(operation.new_value, dict) else None
            if after_laws != before_laws:
                raise HTTPException(403, "Design laws must be changed through the dedicated user-authorized law workflow")
            before_visual = before_state.get("visual_design", {})
            after_visual = (operation.new_value or {}).get("visual_design", {}) if isinstance(operation.new_value, dict) else None
            restored_version_id = (operation.provenance or {}).get("restored_version_id")
            restoring_version = False
            if restored_version_id:
                try:
                    restored_version_id = uuid.UUID(str(restored_version_id))
                except (ValueError, TypeError, AttributeError) as exc:
                    raise HTTPException(403, "Version restoration provenance is invalid") from exc
                restored_version = db.scalar(select(DesignVersion).where(
                    DesignVersion.id == restored_version_id,
                    DesignVersion.project_id == operation.project_id,
                ))
                if not restored_version or restored_version.state != operation.new_value:
                    raise HTTPException(403, "Version restoration must match an existing project snapshot exactly")
                restoring_version = True
            if after_visual != before_visual and not restoring_version:
                raise HTTPException(403, "Visual Design can only change through its validated candidate or version restoration")
        plan_target = operation.target == "metadata.design_plan" or operation.target.startswith("metadata.design_plan.")
        plan_property = bool(operation.property and (operation.property == "metadata.design_plan" or operation.property.startswith("metadata.design_plan.")))
        if plan_target or plan_property:
            if operation.target != "metadata.design_plan" or operation.property not in {None, "metadata.design_plan"}:
                raise HTTPException(422, "Design Plan operations must target metadata.design_plan exactly")
            self._validate_design_plan_operation(db, operation, project)
        wireframe_target = operation.target == "metadata.wireframes" or bool(operation.property and operation.property.startswith("metadata.wireframes"))
        if wireframe_target:
            if operation.target != "metadata.wireframes" or operation.property not in {None, "metadata.wireframes"}:
                raise HTTPException(422, "Wireframe operations must target metadata.wireframes exactly")
            self._validate_wireframe_operation(db, operation, project)
        visual_target = operation.target == "metadata.visual_design" or bool(operation.property and operation.property.startswith("metadata.visual_design"))
        if visual_target:
            if operation.target != "metadata.visual_design" or operation.property not in {None, "metadata.visual_design"}:
                raise HTTPException(422, "Visual Design operations must target metadata.visual_design exactly")
            visual_checks = self._validate_visual_design_operation(db, operation, project)
        else:
            visual_checks = None
        result = {"valid":True, "intent_revision_id":str(operation.intent_id) if operation.intent_id else None, "target":target}
        if visual_checks is not None:
            result["visual_design_checks"] = visual_checks
        return result

    def _validate_visual_design_operation(self, db: Session, operation: DesignOperation, project: Project) -> None:
        if operation.operation_type != OperationType.CREATE or operation.actor != OperationActor.AI:
            raise HTTPException(422, "Visual Design can only be attached through a validated AI proposal")
        if not operation.candidate_id or not operation.ai_run_id or not operation.direction_id:
            raise HTTPException(409, "Visual Design operation is missing candidate, run, or direction provenance")
        run = db.get(AIRun, operation.ai_run_id)
        candidate = db.get(AIOutputCandidate, operation.candidate_id)
        record = db.scalar(select(VisualDesign).where(
            VisualDesign.candidate_id == operation.candidate_id,
            VisualDesign.project_id == operation.project_id,
        ))
        if not run or run.project_id != operation.project_id or run.intent_id != project.current_intent_id or run.status.value != "succeeded":
            raise HTTPException(409, "Visual Design requires a successful run for the current intent revision")
        if not candidate or candidate.run_id != run.id or candidate.project_id != operation.project_id or candidate.intent_id != project.current_intent_id:
            raise HTTPException(409, "Visual Design candidate does not belong to the successful current run")
        if candidate.candidate_type != "visual_design_generation" or candidate.validation_status != "valid":
            raise HTTPException(409, "Visual Design candidate is not schema-validated")
        if not record or record.status not in {VisualDesignStatus.PROPOSED, VisualDesignStatus.PREVIEWED}:
            raise HTTPException(409, "Visual Design candidate is unavailable or no longer eligible")
        state = db.get(DesignState, operation.project_id)
        state_value = state.state if state else DEFAULT_STATE
        try:
            plan_id = uuid.UUID(str((state_value.get("design_plan") or {}).get("record_id")))
            wireframe_id = uuid.UUID(str((state_value.get("wireframes") or {}).get("record_id")))
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(409, "Current approved Design Plan and wireframe are required") from exc
        plan = db.get(DesignPlan, record.design_plan_id)
        wireframe = db.get(WireframeSet, record.wireframe_set_id)
        direction = db.get(DesignDirection, record.direction_id)
        if not plan or plan.id != plan_id or plan.status != DesignPlanStatus.APPROVED:
            raise HTTPException(409, "Visual Design source Design Plan is no longer current")
        if not wireframe or wireframe.id != wireframe_id or wireframe.status != WireframeSetStatus.APPROVED:
            raise HTTPException(409, "Visual Design source wireframe is no longer current")
        if wireframe.design_plan_id != plan.id or record.intent_id != project.current_intent_id:
            raise HTTPException(409, "Visual Design source relationship is stale")
        if not direction or direction.intent_id != project.current_intent_id or direction.status != DirectionStatus.SELECTED:
            raise HTTPException(409, "Visual Design source direction is stale")
        if operation.direction_id != direction.id or operation.intent_id != record.intent_id:
            raise HTTPException(409, "Visual Design operation has mismatched intent or direction provenance")
        from app.services.design_reasoning import DesignReasoningService
        from app.services.visual_designs import VisualDesignWorkflow, stable_digest
        context = DesignReasoningService().build_context(db, operation.project_id)
        expected = {
            "design_plan_id": str(plan.id), "design_plan_digest": stable_digest(plan.plan),
            "wireframe_set_id": str(wireframe.id), "wireframe_digest": stable_digest(wireframe.wireframe),
            "source_context_digest": context["source_manifest"]["content_digest"],
            "source_manifest": context["source_manifest"],
        }
        if (plan.provenance.get("source_manifest") or {}).get("content_digest") != expected["source_context_digest"]:
            raise HTTPException(409, "Approved Design Plan is stale for current reasoning sources")
        if wireframe.provenance.get("source_context_digest") != expected["source_context_digest"]:
            raise HTTPException(409, "Approved wireframe is stale for current reasoning sources")
        if wireframe.provenance.get("design_plan_digest") != expected["design_plan_digest"]:
            raise HTTPException(409, "Approved wireframe is stale for current Design Plan content")
        if any(record.provenance.get(key) != value for key, value in expected.items()):
            raise HTTPException(409, "Visual Design sources changed; generate a new candidate")
        if any((operation.provenance or {}).get(key) != value for key, value in expected.items()):
            raise HTTPException(409, "Visual Design operation provenance does not match its source records")
        if run.context_references != expected:
            raise HTTPException(409, "Visual Design run provenance does not match its source records")
        if not isinstance(operation.new_value, dict) or operation.new_value.get("visual_design") != record.visual_design:
            raise HTTPException(409, "Operation payload does not match the validated Visual Design candidate")
        if candidate.payload != record.visual_design:
            raise HTTPException(409, "Persisted Visual Design record differs from the validated AI candidate")
        if operation.new_value.get("visual_design_id") != str(record.id):
            raise HTTPException(409, "Visual Design operation has mismatched artifact provenance")
        if any(operation.new_value.get(key) != value for key, value in expected.items()):
            raise HTTPException(409, "Visual Design operation has mismatched source references")
        if operation.new_value.get("intent_revision_id") != str(record.intent_id) or operation.new_value.get("direction_id") != str(record.direction_id):
            raise HTTPException(409, "Visual Design operation has stale intent or direction references")
        try:
            validated = VisualDesignOutput.model_validate(record.visual_design, strict=True).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(409, "Persisted Visual Design candidate no longer satisfies its schema") from exc
        if validated != record.visual_design:
            raise HTTPException(409, "Persisted Visual Design candidate is not canonical")
        result = VisualDesignWorkflow.validate_semantics(plan, wireframe, record.visual_design)
        if "design_laws" in operation.new_value:
            raise HTTPException(403, "Visual Design operations cannot modify Design Laws")
        return result

    def _validate_design_plan_operation(self, db: Session, operation: DesignOperation, project: Project) -> None:
        if operation.operation_type != OperationType.CREATE or operation.actor != OperationActor.AI:
            raise HTTPException(422, "Design Plan state can only be added through a validated AI proposal operation")
        if not operation.candidate_id or not operation.ai_run_id or not operation.direction_id:
            raise HTTPException(409, "Design Plan operation is missing candidate, run, or direction provenance")
        run = db.get(AIRun, operation.ai_run_id)
        candidate = db.get(AIOutputCandidate, operation.candidate_id)
        direction = db.scalar(select(DesignDirection).where(
            DesignDirection.id == operation.direction_id,
            DesignDirection.project_id == operation.project_id,
            DesignDirection.intent_id == project.current_intent_id,
            DesignDirection.status == DirectionStatus.SELECTED,
        ))
        record = db.scalar(select(DesignPlan).where(
            DesignPlan.candidate_id == operation.candidate_id,
            DesignPlan.project_id == operation.project_id,
            DesignPlan.intent_id == project.current_intent_id,
            DesignPlan.direction_id == operation.direction_id,
        ))
        if not run or run.project_id != operation.project_id or run.intent_id != project.current_intent_id or run.status.value != "succeeded":
            raise HTTPException(409, "Design Plan requires a successful AI Run for the current intent revision")
        if not candidate or candidate.run_id != run.id or candidate.project_id != operation.project_id or candidate.intent_id != project.current_intent_id:
            raise HTTPException(409, "Design Plan candidate does not belong to the successful current AI Run")
        if candidate.candidate_type != "design_plan_generation" or candidate.validation_status != "valid":
            raise HTTPException(409, "Design Plan candidate is not schema-validated")
        if not direction:
            raise HTTPException(409, "The selected direction changed or is stale")
        if not record or record.status not in {DesignPlanStatus.PROPOSED, DesignPlanStatus.PREVIEWED}:
            raise HTTPException(409, "Design Plan record is unavailable or no longer eligible")
        if record.plan != candidate.payload or record.confidence != candidate.payload.get("confidence"):
            raise HTTPException(409, "Persisted Design Plan differs from its validated candidate")
        if record.provenance.get("candidate_id") not in {None, str(candidate.id)}:
            raise HTTPException(409, "Design Plan record has mismatched candidate provenance")
        if run.context_references.get("direction_id") != str(direction.id):
            raise HTTPException(409, "AI Run context does not match the current selected direction")
        if not isinstance(operation.new_value, dict) or operation.new_value.get("plan") != candidate.payload:
            raise HTTPException(409, "Operation payload does not match the validated Design Plan candidate")
        if operation.new_value.get("intent_revision_id") != str(project.current_intent_id) or operation.new_value.get("direction_id") != str(direction.id):
            raise HTTPException(409, "Design Plan payload has stale intent or direction provenance")
        provenance = operation.provenance or {}
        manifest = provenance.get("source_manifest")
        if not isinstance(manifest, dict) or manifest != record.provenance.get("source_manifest"):
            raise HTTPException(409, "Design Plan source manifest is missing or has changed")
        run_manifest = (run.context_references or {}).get("source_manifest")
        if run_manifest != manifest:
            raise HTTPException(409, "Design Plan source manifest does not match the AI Run context")
        if sorted(map(str, provenance.get("requirement_ids", []))) != sorted(map(str, manifest.get("requirements", []))):
            raise HTTPException(409, "Design Plan requirement references do not match its source manifest")
        if sorted(map(str, provenance.get("research_ids", []))) != sorted(map(str, manifest.get("research", []))):
            raise HTTPException(409, "Design Plan research references do not match its source manifest")
        intent_ids = self._parse_source_ids(manifest.get("intent", []), "intent")
        if intent_ids != [project.current_intent_id]:
            raise HTTPException(409, "Design Plan source manifest uses a stale intent revision")
        requirement_ids = self._parse_source_ids(manifest.get("requirements", []), "requirement")
        requirements = db.scalars(select(DesignRequirement).where(
            DesignRequirement.id.in_(requirement_ids),
            DesignRequirement.project_id == operation.project_id,
            DesignRequirement.intent_id == project.current_intent_id,
            DesignRequirement.status.not_in([RequirementStatus.REJECTED, RequirementStatus.SUPERSEDED]),
        )).all() if requirement_ids else []
        if len(requirements) != len(set(requirement_ids)):
            raise HTTPException(409, "Design Plan references a stale or unavailable requirement")
        current_requirement_ids = set(db.scalars(select(DesignRequirement.id).where(
            DesignRequirement.project_id == operation.project_id,
            DesignRequirement.intent_id == project.current_intent_id,
            DesignRequirement.status.not_in([RequirementStatus.REJECTED, RequirementStatus.SUPERSEDED]),
        )))
        if set(requirement_ids) != current_requirement_ids:
            raise HTTPException(409, "Current requirements changed; generate a new Design Plan candidate")
        evidence_ids = self._parse_source_ids(manifest.get("research", []), "research evidence")
        evidence = db.scalars(select(ResearchEvidence).where(
            ResearchEvidence.id.in_(evidence_ids),
            ResearchEvidence.project_id == operation.project_id,
            ResearchEvidence.intent_id == project.current_intent_id,
        )).all() if evidence_ids else []
        if len(evidence) != len(set(evidence_ids)):
            raise HTTPException(409, "Design Plan references stale or unavailable research evidence")
        if any(row.trust == EvidenceTrust.UNTRUSTED for row in evidence):
            raise HTTPException(409, "Design Plan references untrusted research evidence")
        current_evidence_ids = set(db.scalars(select(ResearchEvidence.id).where(
            ResearchEvidence.project_id == operation.project_id,
            ResearchEvidence.intent_id == project.current_intent_id,
            ResearchEvidence.trust.in_({EvidenceTrust.AUTHORITATIVE, EvidenceTrust.RELIABLE, EvidenceTrust.REVIEWED}),
        )))
        if set(evidence_ids) != current_evidence_ids:
            raise HTTPException(409, "Trusted research context changed; generate a new Design Plan candidate")
        law_ids = self._parse_source_ids(manifest.get("design_laws", []), "design law")
        law_rows = db.scalars(select(DesignLaw).where(DesignLaw.project_id == operation.project_id, DesignLaw.active.is_(True))).all()
        current_law_ids = [row.id for row in law_rows]
        if set(law_ids) != set(current_law_ids):
            raise HTTPException(409, "Design Plan design-law context changed; generate a new candidate")
        question_ids = self._parse_source_ids(manifest.get("questions", []), "question")
        current_question_ids = list(db.scalars(select(Question.id).where(
            Question.project_id == operation.project_id,
            Question.intent_id == project.current_intent_id,
            Question.status == QuestionStatus.OPEN,
            (Question.priority.in_([QuestionPriority.CRITICAL, QuestionPriority.HIGH]) | (Question.impact_score >= 70)),
        )))
        if set(question_ids) != set(current_question_ids):
            raise HTTPException(409, "High-impact question context changed; generate a new candidate")
        plan_payload = operation.new_value["plan"]
        mapped_requirements = {mapping.get("requirement_id") for mapping in plan_payload.get("requirements_mapping", [])}
        if mapped_requirements != {str(value) for value in requirement_ids}:
            raise HTTPException(409, "Design Plan requirement mappings do not cover its current source manifest")
        if any(mapping.get("evidence_id") not in {str(value) for value in evidence_ids} for mapping in plan_payload.get("research_mapping", [])):
            raise HTTPException(409, "Design Plan maps research outside its current source manifest")
        law_considerations = {item.get("id"): item for item in plan_payload.get("design_laws_considered", [])}
        if set(law_considerations) != {str(value) for value in law_ids}:
            raise HTTPException(409, "Design Plan law consideration does not cover the current source manifest")
        law_by_id = {str(row.id): row for row in law_rows}
        for law_id, item in law_considerations.items():
            if item.get("law") != law_by_id[law_id].rule:
                raise HTTPException(409, "Design Plan altered an authoritative Design Law")
            if any(word in item.get("consideration", "").casefold() for word in ("optional", "ignore", "waive", "weaken", "override")):
                raise HTTPException(409, "Design Plan cannot weaken or reinterpret an authoritative Design Law")
            conflict = item.get("conflict", "").casefold()
            if not any(phrase in conflict for phrase in ("no conflict", "none identified", "not identified")):
                if not any(risk.get("source") == f"design_law:{law_id}" for risk in plan_payload.get("risks", [])):
                    raise HTTPException(409, "Design Law conflicts must be surfaced as a plan risk")
        if {item.get("question_id") for item in plan_payload.get("unresolved_questions", [])} != {str(value) for value in question_ids}:
            raise HTTPException(409, "Design Plan uncertainty does not cover the current high-impact questions")
        from app.services.design_reasoning import DesignReasoningService
        current_context = DesignReasoningService().build_context(db, operation.project_id)
        if manifest.get("content_digest") != current_context["source_manifest"].get("content_digest"):
            raise HTTPException(409, "Design Plan source content changed; generate a new candidate")

    def _validate_wireframe_operation(self, db: Session, operation: DesignOperation, project: Project) -> None:
        if operation.operation_type != OperationType.CREATE or operation.actor != OperationActor.AI:
            raise HTTPException(422, "Wireframes can only be attached through a validated AI proposal")
        if not operation.candidate_id or not operation.ai_run_id or not operation.direction_id:
            raise HTTPException(409, "Wireframe operation is missing candidate, run, or direction provenance")
        run = db.get(AIRun, operation.ai_run_id)
        candidate = db.get(AIOutputCandidate, operation.candidate_id)
        row = db.scalar(select(WireframeSet).where(
            WireframeSet.candidate_id == operation.candidate_id,
            WireframeSet.project_id == operation.project_id,
        ))
        if not run or run.project_id != operation.project_id or run.intent_id != project.current_intent_id or run.status.value != "succeeded":
            raise HTTPException(409, "Wireframes require a successful run for the current intent revision")
        if not candidate or candidate.run_id != run.id or candidate.project_id != operation.project_id or candidate.intent_id != project.current_intent_id:
            raise HTTPException(409, "Wireframe candidate does not belong to the successful current run")
        if candidate.candidate_type != "wireframe_generation" or candidate.validation_status != "valid":
            raise HTTPException(409, "Wireframe candidate is not schema-validated")
        if not row or row.status not in {WireframeSetStatus.PROPOSED, WireframeSetStatus.PREVIEWED}:
            raise HTTPException(409, "Wireframe candidate is unavailable or no longer eligible")
        state = db.get(DesignState, operation.project_id)
        approved_plan_id = ((state.state if state else DEFAULT_STATE).get("design_plan") or {}).get("record_id")
        plan = db.get(DesignPlan, row.design_plan_id)
        direction = db.get(DesignDirection, row.direction_id)
        if not plan or plan.status != DesignPlanStatus.APPROVED or str(plan.id) != str(approved_plan_id):
            raise HTTPException(409, "Wireframe source Design Plan is no longer the approved plan")
        if row.intent_id != project.current_intent_id:
            raise HTTPException(409, "Wireframe source intent is stale")
        if not direction or direction.intent_id != project.current_intent_id or direction.status != DirectionStatus.SELECTED:
            raise HTTPException(409, "Wireframe source direction is stale")
        if operation.direction_id != direction.id or operation.intent_id != row.intent_id:
            raise HTTPException(409, "Wireframe operation does not match its persisted direction and intent")
        from app.services.design_reasoning import DesignReasoningService
        context = DesignReasoningService().build_context(db, operation.project_id)
        if row.provenance.get("source_context_digest") != context["source_manifest"]["content_digest"]:
            raise HTTPException(409, "Wireframe reasoning context changed; generate a new candidate")
        from app.services.wireframes import stable_digest
        if row.provenance.get("design_plan_digest") != stable_digest(plan.plan):
            raise HTTPException(409, "Approved Design Plan content changed; generate a new wireframe candidate")
        expected_run_context = {
            "design_plan_id": str(plan.id),
            "design_plan_digest": row.provenance.get("design_plan_digest"),
            "source_context_digest": row.provenance.get("source_context_digest"),
            "source_manifest": row.provenance.get("source_manifest"),
        }
        if run.context_references != expected_run_context:
            raise HTTPException(409, "Wireframe run provenance does not match the persisted candidate")
        if not isinstance(operation.new_value, dict) or operation.new_value.get("wireframe") != row.wireframe:
            raise HTTPException(409, "Operation payload does not match the validated wireframe candidate")
        if operation.new_value.get("wireframe_set_id") != str(row.id) or operation.new_value.get("design_plan_id") != str(plan.id):
            raise HTTPException(409, "Wireframe operation has mismatched plan or artifact provenance")
        if operation.new_value.get("intent_revision_id") != str(project.current_intent_id) or operation.new_value.get("direction_id") != str(direction.id):
            raise HTTPException(409, "Wireframe operation uses stale intent or direction provenance")
        try:
            validated = WireframeOutput.model_validate(row.wireframe, strict=True).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(409, "Persisted wireframe candidate no longer satisfies its schema") from exc
        if validated != row.wireframe:
            raise HTTPException(409, "Persisted wireframe candidate is not canonical")
        expected_pages = {str(item.get("id")) for item in plan.plan.get("pages", [])}
        received_pages = [str(item.get("page_id")) for item in row.wireframe.get("pages", [])]
        if set(received_pages) != expected_pages or len(received_pages) != len(expected_pages):
            raise HTTPException(409, "Wireframe candidate no longer covers the approved plan pages")

    @staticmethod
    def _parse_source_ids(values, label: str) -> list[uuid.UUID]:
        if not isinstance(values, list):
            raise HTTPException(409, f"Design Plan {label} source manifest is invalid")
        try:
            return [uuid.UUID(str(value)) for value in values]
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(409, f"Design Plan {label} source manifest contains an invalid ID") from exc

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
        elif operation.operation_type == OperationType.CREATE and operation.target == "metadata.design_plan":
            after["design_plan"] = copy.deepcopy(operation.new_value)
        elif operation.operation_type == OperationType.CREATE and operation.target == "metadata.wireframes":
            after["wireframes"] = {
                **copy.deepcopy(operation.new_value),
                "record_id": operation.new_value.get("wireframe_set_id"),
            }
        elif operation.operation_type == OperationType.CREATE and operation.target == "metadata.visual_design":
            after["visual_design"] = {
                **copy.deepcopy(operation.new_value),
                "record_id": operation.new_value.get("visual_design_id"),
            }
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
        risks = []
        if operation.target == "metadata.wireframes" and isinstance(operation.new_value, dict):
            wireframe = operation.new_value.get("wireframe", {})
            if float(wireframe.get("confidence", 0)) < 0.6:
                risks.append("Wireframe candidate confidence is below 0.6")
            for page in wireframe.get("pages", []):
                if not page.get("responsive_notes"):
                    risks.append(f"Page {page.get('page_id')} has no responsive behavior notes")
                if not page.get("accessibility_notes"):
                    risks.append(f"Page {page.get('page_id')} has no accessibility notes")
        if operation.target == "metadata.visual_design" and isinstance(operation.new_value, dict):
            visual = operation.new_value.get("visual_design", {})
            if float(visual.get("confidence", 0)) < 0.6:
                risks.append("Visual design candidate confidence is below 0.6")
            risks.extend(f"Unresolved design decision: {item}" for item in visual.get("unresolved_decisions", []))
            risks.extend(f"Assumption requires review: {item}" for item in visual.get("assumptions", []))
            risks.extend(f"Visual design risk: {item}" for item in visual.get("risks", []))
            risks.extend(f"Untrusted asset reference requires review: {item.get('asset_ref')}" for item in visual.get("assets", []) if not item.get("trusted", False))
            risks.append("Automated contrast checks cover declared color pairs only and do not establish full accessibility conformance")
        preview = OperationPreview(operation_id=operation.id, base_version_id=base, before_state=before, after_state=after,
            impact={"changed_paths":_diff_paths(before, after), "scope":operation.scope, "risks":risks, "requires_user_approval":True},
            provenance={"validation":validation, "source":operation.source.value, "intent_revision_id":str(operation.intent_id) if operation.intent_id else None}, state_digest=digest)
        db.add(preview); operation.status=OperationStatus.PREVIEWED
        if operation.candidate_id:
            plan_record = db.scalar(select(DesignPlan).where(DesignPlan.candidate_id == operation.candidate_id))
            if plan_record and plan_record.status == DesignPlanStatus.PROPOSED:
                plan_record.status = DesignPlanStatus.PREVIEWED
            wireframe_record = db.scalar(select(WireframeSet).where(WireframeSet.candidate_id == operation.candidate_id))
            if wireframe_record and wireframe_record.status == WireframeSetStatus.PROPOSED:
                wireframe_record.status = WireframeSetStatus.PREVIEWED
            visual_record = db.scalar(select(VisualDesign).where(VisualDesign.candidate_id == operation.candidate_id))
            if visual_record and visual_record.status == VisualDesignStatus.PROPOSED:
                visual_record.status = VisualDesignStatus.PREVIEWED
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
        if operation.candidate_id and not approved:
            plan_record = db.scalar(select(DesignPlan).where(DesignPlan.candidate_id == operation.candidate_id))
            if plan_record:
                plan_record.status = DesignPlanStatus.REJECTED
            wireframe_record = db.scalar(select(WireframeSet).where(WireframeSet.candidate_id == operation.candidate_id))
            if wireframe_record:
                wireframe_record.status = WireframeSetStatus.REJECTED
            visual_record = db.scalar(select(VisualDesign).where(VisualDesign.candidate_id == operation.candidate_id))
            if visual_record:
                visual_record.status = VisualDesignStatus.REJECTED
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
        plan_record = None
        wireframe_record = None
        visual_record = None
        if operation.candidate_id:
            plan_record = db.scalar(select(DesignPlan).where(DesignPlan.candidate_id == operation.candidate_id).with_for_update())
            if plan_record:
                direction = db.get(DesignDirection, plan_record.direction_id)
                now = datetime.now(timezone.utc)
                next_state.setdefault("design_plan", {})["approved_at"] = now.isoformat()
                next_state["design_plan"]["approved_by"] = actor.actor_id
                next_state["design_plan"]["record_id"] = str(plan_record.id)
                plan_record.status = DesignPlanStatus.APPROVED
                plan_record.approved_at = now
                plan_record.approved_by = actor.actor_id
                previously_approved = db.scalars(select(DesignPlan).where(
                    DesignPlan.project_id == operation.project_id,
                    DesignPlan.status == DesignPlanStatus.APPROVED,
                    DesignPlan.id != plan_record.id,
                ).with_for_update()).all()
                for previous in previously_approved:
                    previous.status = DesignPlanStatus.SUPERSEDED
                if next_state.get("wireframes"):
                    next_state["wireframes"] = {}
                next_state["visual_design"] = {}
                stale_wireframes = db.scalars(select(WireframeSet).where(
                    WireframeSet.project_id == operation.project_id,
                    WireframeSet.status == WireframeSetStatus.APPROVED,
                    WireframeSet.design_plan_id != plan_record.id,
                ).with_for_update()).all()
                for previous in stale_wireframes:
                    previous.status = WireframeSetStatus.SUPERSEDED
                stale_visuals = db.scalars(select(VisualDesign).where(
                    VisualDesign.project_id == operation.project_id,
                    VisualDesign.status == VisualDesignStatus.APPROVED,
                ).with_for_update()).all()
                for previous in stale_visuals:
                    previous.status = VisualDesignStatus.SUPERSEDED
            wireframe_record = db.scalar(select(WireframeSet).where(WireframeSet.candidate_id == operation.candidate_id).with_for_update())
            if wireframe_record:
                now = datetime.now(timezone.utc)
                wireframe_record.status = WireframeSetStatus.APPROVED
                wireframe_record.approved_at = now
                wireframe_record.approved_by = actor.actor_id
                previous_wireframes = db.scalars(select(WireframeSet).where(
                    WireframeSet.project_id == operation.project_id,
                    WireframeSet.status == WireframeSetStatus.APPROVED,
                    WireframeSet.id != wireframe_record.id,
                ).with_for_update()).all()
                for previous in previous_wireframes:
                    previous.status = WireframeSetStatus.SUPERSEDED
                next_state["visual_design"] = {}
                previous_visuals = db.scalars(select(VisualDesign).where(
                    VisualDesign.project_id == operation.project_id,
                    VisualDesign.status == VisualDesignStatus.APPROVED,
                ).with_for_update()).all()
                for previous in previous_visuals:
                    previous.status = VisualDesignStatus.SUPERSEDED
            visual_record = db.scalar(select(VisualDesign).where(VisualDesign.candidate_id == operation.candidate_id).with_for_update())
            if visual_record:
                now = datetime.now(timezone.utc)
                visual_record.status = VisualDesignStatus.APPROVED
                visual_record.approved_at = now
                visual_record.approved_by = actor.actor_id
                previous_visuals = db.scalars(select(VisualDesign).where(
                    VisualDesign.project_id == operation.project_id,
                    VisualDesign.status == VisualDesignStatus.APPROVED,
                    VisualDesign.id != visual_record.id,
                ).with_for_update()).all()
                for previous in previous_visuals:
                    previous.status = VisualDesignStatus.SUPERSEDED
        if operation.operation_type == OperationType.REPLACE and (operation.property or operation.target) == "*" and (operation.provenance or {}).get("restored_version_id"):
            self._restore_artifact_statuses(db, operation.project_id, next_state, actor)
        if not current: current = create_initial_design_state(db, operation.project_id)
        updated = update_design_state(db, operation.project_id, next_state, operation.reason)
        operation.status = OperationStatus.APPLIED
        operation.provenance = {**(operation.provenance or {}), "applied_version_id":str(updated.current_version_id), "applied_at":datetime.now(timezone.utc).isoformat(), "validation":validation}
        if operation.operation_type == OperationType.SELECT_DIRECTION:
            self._apply_direction_selection(db, operation, actor)
        self._event(db, operation, actor, "operation.applied", "Operation applied atomically", {"version_id":str(updated.current_version_id)})
        candidate = (operation.provenance or {}).get("memory_candidate", {})
        if plan_record:
            direction = db.get(DesignDirection, plan_record.direction_id)
            page_count = len(plan_record.plan.get("pages", []))
            flow_names = [flow.get("name", "user flow") for flow in plan_record.plan.get("user_flows", [])]
            flow_summary = f" and the {flow_names[0]} flow" if flow_names else ""
            content = f"Approved Design Plan for the selected {direction.name if direction else 'design'} direction, covering {page_count} pages{flow_summary}."
            category = "design_plan"
        elif wireframe_record:
            page_count = len(wireframe_record.wireframe.get("pages", []))
            content = f"Approved wireframe set for {page_count} pages from Design Plan {wireframe_record.design_plan_id}."
            category = "wireframe_set"
        elif visual_record:
            content = f"Approved visual design for {len(visual_record.visual_design.get('pages', []))} pages from wireframe {visual_record.wireframe_set_id}."
            category = "visual_design"
            visual_record.provenance = {
                **(visual_record.provenance or {}),
                "approved_by": actor.actor_id,
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "applied_version_id": str(updated.current_version_id),
                "validation": validation,
            }
            goals = visual_record.visual_design.get("goals", [])
            if goals:
                content = f"Approved visual direction: {goals[0]} Rationale: {visual_record.visual_design.get('rationale', '')} Approved through operation {operation.id}."
        else:
            content = candidate.get("content") or f"Applied {operation.operation_type.value} at {operation.property or operation.target}: {operation.reason}"
            category = candidate.get("category", "design_change")
        memory = db.scalar(select(DesignMemory).where(DesignMemory.source_operation_id == operation.id))
        if memory is None:
            db.add(DesignMemory(project_id=operation.project_id, category=category, content=content, trust=MemoryTrust.USER_APPROVED,
                source_operation_id=operation.id, provenance={"operation_id":str(operation.id),"source_id":str(self._direction_id(operation)) if operation.operation_type == OperationType.SELECT_DIRECTION else str(operation.id),"actor_id":actor.actor_id,"actor_type":actor.actor_type.value,
                "intent_revision_id":str(operation.intent_id) if operation.intent_id else None,"created_version_id":str(updated.current_version_id),
                "source":operation.source.value,"ai_run_id":str(operation.ai_run_id) if operation.ai_run_id else None,
                "direction_id":str(plan_record.direction_id) if plan_record else (str(operation.direction_id) if operation.direction_id else None),
                "source_manifest":(operation.provenance or {}).get("source_manifest") if (plan_record or wireframe_record or visual_record) else None,
                "design_plan_id":str(visual_record.design_plan_id) if visual_record else (str(wireframe_record.design_plan_id) if wireframe_record else None),
                "wireframe_set_id":str(visual_record.wireframe_set_id) if visual_record else None,
                "visual_design_id":str(visual_record.id) if visual_record else None,
                "validation":validation}))
        db.flush()
        return operation

    def execute_confirmed_user_request(self, db: Session, project_id: uuid.UUID, data: OperationCreate, actor: ActorContext) -> DesignOperation:
        """Compatibility path for explicit user updates; still traverses executor stages."""
        operation = self.propose(db, project_id, data, actor)
        preview = self.preview(db, operation.id, actor)
        self.approve(db, operation.id, preview.id, actor, True)
        return self.apply(db, operation.id, actor)

    @staticmethod
    def _restore_artifact_statuses(db: Session, project_id: uuid.UUID, state: dict, actor: ActorContext) -> None:
        """Reactivate only artifacts referenced by a user-approved restored snapshot."""
        def record_id(section: str) -> uuid.UUID | None:
            raw = ((state.get(section) or {}).get("record_id"))
            if raw is None:
                return None
            try:
                return uuid.UUID(str(raw))
            except (ValueError, TypeError, AttributeError) as exc:
                raise HTTPException(409, f"Restored {section} reference is invalid") from exc

        plan_id = record_id("design_plan")
        wireframe_id = record_id("wireframes")
        visual_id = record_id("visual_design")
        plan = db.scalar(select(DesignPlan).where(DesignPlan.id == plan_id, DesignPlan.project_id == project_id)) if plan_id else None
        wireframe = db.scalar(select(WireframeSet).where(WireframeSet.id == wireframe_id, WireframeSet.project_id == project_id)) if wireframe_id else None
        visual = db.scalar(select(VisualDesign).where(VisualDesign.id == visual_id, VisualDesign.project_id == project_id)) if visual_id else None
        if plan_id and (not plan or plan.status not in {DesignPlanStatus.APPROVED, DesignPlanStatus.SUPERSEDED}):
            raise HTTPException(409, "Restored Design Plan is unavailable or was never approved")
        if wireframe_id and (not wireframe or wireframe.status not in {WireframeSetStatus.APPROVED, WireframeSetStatus.SUPERSEDED}):
            raise HTTPException(409, "Restored wireframe is unavailable or was never approved")
        if visual_id and (not visual or visual.status not in {VisualDesignStatus.APPROVED, VisualDesignStatus.SUPERSEDED}):
            raise HTTPException(409, "Restored Visual Design is unavailable or was never approved")
        if wireframe and (not plan or wireframe.design_plan_id != plan.id):
            raise HTTPException(409, "Restored wireframe does not belong to the restored Design Plan")
        if visual and (not plan or not wireframe or visual.design_plan_id != plan.id or visual.wireframe_set_id != wireframe.id):
            raise HTTPException(409, "Restored Visual Design does not match the restored source artifacts")
        plan_rows = db.scalars(select(DesignPlan).where(DesignPlan.project_id == project_id, DesignPlan.status == DesignPlanStatus.APPROVED).with_for_update()).all()
        wireframe_rows = db.scalars(select(WireframeSet).where(WireframeSet.project_id == project_id, WireframeSet.status == WireframeSetStatus.APPROVED).with_for_update()).all()
        visual_rows = db.scalars(select(VisualDesign).where(VisualDesign.project_id == project_id, VisualDesign.status == VisualDesignStatus.APPROVED).with_for_update()).all()
        for row in plan_rows:
            if not plan or row.id != plan.id:
                row.status = DesignPlanStatus.SUPERSEDED
        for row in wireframe_rows:
            if not wireframe or row.id != wireframe.id:
                row.status = WireframeSetStatus.SUPERSEDED
        for row in visual_rows:
            if not visual or row.id != visual.id:
                row.status = VisualDesignStatus.SUPERSEDED
        now = datetime.now(timezone.utc)
        for row in (plan, wireframe, visual):
            if row is not None:
                row.status = row.status.__class__.APPROVED
                row.approved_at = row.approved_at or now
                row.approved_by = row.approved_by or actor.actor_id
        db.flush()

    def _apply_direction_selection(self, db: Session, operation: DesignOperation, actor: ActorContext) -> None:
        direction = db.get(DesignDirection, self._direction_id(operation))
        if not direction or direction.intent_id != operation.intent_id: raise HTTPException(409, "Direction became stale")
        old_selected = db.scalars(select(DesignDirection).where(DesignDirection.project_id == operation.project_id, DesignDirection.status == DirectionStatus.SELECTED)).all()
        for old in old_selected: old.status = DirectionStatus.ARCHIVED
        if old_selected:
            db.flush()
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
