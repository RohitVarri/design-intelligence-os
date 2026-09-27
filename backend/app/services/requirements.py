"""Requirements retain whether they came from the user, inference, research, or system."""
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.intent import IntentStatus, ProjectIntent
from app.models.project import Project
from app.models.requirement import DesignRequirement, RequirementCategory, RequirementSource
from app.models.research_evidence import ResearchEvidence
from app.schemas.requirement import RequirementCreate
from app.services.intent import IntentExtractionService
from app.services.questions import QuestionService

class RequirementService:
    def _make(self, db: Session, project_id: uuid.UUID, intent_id: uuid.UUID | None, data: RequirementCreate, *, generated: bool = False) -> DesignRequirement:
        created_at = datetime.now(timezone.utc).isoformat()
        provenance: dict
        if data.source == RequirementSource.USER:
            provenance = {"source_type": "user_request" if generated else "user_submitted_requirement", "source_id": str(intent_id) if generated and intent_id else None, "source_reference": "ProjectIntent" if generated else "requirement_api_payload", "created_by": "user", "created_at": created_at}
        elif data.source == RequirementSource.INFERRED:
            provenance = {"source_type": "deterministic_inference" if generated else "user_submitted_inference", "source_id": str(intent_id) if generated and intent_id else None, "source_reference": "ProjectIntent" if generated else "requirement_api_payload", "created_by": "system" if generated else "user", "created_at": created_at}
        elif data.source == RequirementSource.RESEARCH:
            if not data.evidence_id: raise HTTPException(422, "evidence_id is required for a research-sourced requirement")
            evidence = db.scalar(select(ResearchEvidence).where(ResearchEvidence.id == data.evidence_id, ResearchEvidence.project_id == project_id, ResearchEvidence.intent_id == intent_id))
            if not evidence: raise HTTPException(404, "Research evidence not found")
            provenance = {"source_type": "research", "source_id": str(evidence.id), "source_reference": evidence.source_url or "ResearchEvidence record", "created_by": "research", "created_at": created_at}
        else:
            provenance = {"source_type": "system", "source_id": None, "source_reference": "system_requirement", "created_by": "system", "created_at": created_at}
        obj = DesignRequirement(project_id=project_id, intent_id=intent_id, requirement=data.requirement, category=data.category,
            priority=data.priority, source=data.source, rationale=data.rationale, status=data.status, confidence=data.confidence, provenance=provenance)
        db.add(obj); db.flush(); return obj

    def create(self, db: Session, project_id: uuid.UUID, data: RequirementCreate) -> DesignRequirement:
        if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
        intent = None
        try: intent = IntentExtractionService.latest(db, project_id)
        except HTTPException as exc:
            if exc.status_code != 404: raise
        return self._make(db, project_id, intent.id if intent else None, data)

    def list_for_project(self, db: Session, project_id: uuid.UUID) -> list[DesignRequirement]:
        if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
        return list(db.scalars(select(DesignRequirement).where(DesignRequirement.project_id == project_id).order_by(DesignRequirement.created_at.desc())))

    def generate_from_intent(self, db: Session, project_id: uuid.UUID) -> list[DesignRequirement]:
        intent = IntentExtractionService.latest(db, project_id)
        existing = {row.requirement for row in db.scalars(select(DesignRequirement).where(DesignRequirement.project_id == project_id, DesignRequirement.intent_id == intent.id))}
        field_sources = (intent.provenance or {}).get("field_sources", {})
        proposals: list[tuple[str, RequirementCategory, RequirementSource, str, float]] = []
        if intent.business_or_product_goal:
            source = RequirementSource.USER if field_sources.get("business_or_product_goal", {}).get("source_type") in {"user_request", "user_answer"} else RequirementSource.INFERRED
            proposals.append((f"Support the stated project goal: {intent.business_or_product_goal}", RequirementCategory.BUSINESS, source, "Derived from the structured project goal.", field_sources.get("business_or_product_goal", {}).get("confidence", 0.55)))
        if intent.desired_user_action:
            source = RequirementSource.USER if field_sources.get("desired_user_action", {}).get("source_type") in {"user_request", "user_answer"} else RequirementSource.INFERRED
            proposals.append((f"Enable the desired user action: {intent.desired_user_action}", RequirementCategory.FUNCTIONAL, source, "Derived from the stated or clarified desired user action.", field_sources.get("desired_user_action", {}).get("confidence", 0.55)))
        for preference in intent.visual_preferences:
            source = RequirementSource.USER if field_sources.get("visual_preferences", {}).get("source_type") in {"user_request", "user_answer"} else RequirementSource.INFERRED
            proposals.append((f"Consider the visual preference: {preference}", RequirementCategory.VISUAL, source, "Preserves a visual preference without forcing it into every direction.", field_sources.get("visual_preferences", {}).get("confidence", 0.6)))
        for item in intent.accessibility_requirements:
            proposals.append((f"Address the requested accessibility consideration: {item}", RequirementCategory.ACCESSIBILITY, RequirementSource.USER, "Explicitly present in the user's request.", 0.95))
        evidence_rows = db.scalars(select(ResearchEvidence).where(ResearchEvidence.project_id == project_id, ResearchEvidence.intent_id == intent.id, ResearchEvidence.related_requirement.is_not(None), ResearchEvidence.trust != "untrusted")).all()
        results = []
        for sentence, category, source, rationale, confidence in proposals:
            if sentence in existing: continue
            results.append(self._make(db, project_id, intent.id, RequirementCreate(requirement=sentence, category=category, source=source, rationale=rationale, confidence=confidence), generated=True))
        for evidence in evidence_rows:
            sentence = evidence.related_requirement
            if sentence in existing: continue
            results.append(self._make(db, project_id, intent.id, RequirementCreate(requirement=sentence, category=RequirementCategory.UX, source=RequirementSource.RESEARCH, rationale="Research-derived proposal; review the evidence and tradeoffs before treating it as a design instruction.", confidence=evidence.confidence or 0.0, evidence_id=evidence.id), generated=True))
        if not IntentExtractionService.missing_information(intent) and not QuestionService().list_for_project(db, project_id, open_only=True):
            IntentExtractionService.transition_status(intent, IntentStatus.READY_FOR_DIRECTION, actor="system", reason="Required intent fields and question policy are satisfied")
        db.flush(); return results

requirement_service = RequirementService()
