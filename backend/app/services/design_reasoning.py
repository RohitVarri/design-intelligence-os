"""Build source-checked, revision-scoped context for design reasoning."""
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.design_law import DesignLaw
from app.models.direction import DesignDirection, DirectionStatus
from app.models.intent import ProjectIntent
from app.models.project import Project
from app.models.question import Question, QuestionPriority, QuestionStatus
from app.models.research_evidence import EvidenceTrust, ResearchEvidence
from app.models.requirement import DesignRequirement, RequirementStatus
from app.schemas.design_plan import DesignReasoningContextRead


TRUSTED_REASONING_EVIDENCE = {
    EvidenceTrust.AUTHORITATIVE,
    EvidenceTrust.RELIABLE,
    EvidenceTrust.REVIEWED,
}


class DesignReasoningService:
    """Resolve exact current inputs; callers cannot submit authoritative source IDs."""

    def build_context(self, db: Session, project_id: uuid.UUID) -> dict:
        project = db.get(Project, project_id)
        if project is None:
            raise HTTPException(404, "Project not found")
        if project.current_intent_id is None:
            raise HTTPException(409, "A current intent revision is required before generating a Design Plan.")

        intent = db.scalar(
            select(ProjectIntent).where(
                ProjectIntent.id == project.current_intent_id,
                ProjectIntent.project_id == project_id,
            )
        )
        if intent is None:
            raise HTTPException(409, "The current intent revision is unavailable.")
        direction = db.scalar(
            select(DesignDirection).where(
                DesignDirection.project_id == project_id,
                DesignDirection.intent_id == intent.id,
                DesignDirection.status == DirectionStatus.SELECTED,
            )
        )
        if direction is None:
            raise HTTPException(409, "A selected design direction is required before generating a Design Plan.")

        requirements = list(
            db.scalars(
                select(DesignRequirement)
                .where(
                    DesignRequirement.project_id == project_id,
                    DesignRequirement.intent_id == intent.id,
                    DesignRequirement.status.not_in([RequirementStatus.REJECTED, RequirementStatus.SUPERSEDED]),
                )
                .order_by(DesignRequirement.created_at, DesignRequirement.id)
            )
        )
        evidence = list(
            db.scalars(
                select(ResearchEvidence)
                .where(
                    ResearchEvidence.project_id == project_id,
                    ResearchEvidence.intent_id == intent.id,
                    ResearchEvidence.trust.in_(TRUSTED_REASONING_EVIDENCE),
                )
                .order_by(ResearchEvidence.created_at, ResearchEvidence.id)
            )
        )
        laws = list(
            db.scalars(
                select(DesignLaw)
                .where(DesignLaw.project_id == project_id, DesignLaw.active.is_(True))
                .order_by(DesignLaw.created_at, DesignLaw.id)
            )
        )
        questions = list(
            db.scalars(
                select(Question)
                .where(
                    Question.project_id == project_id,
                    Question.intent_id == intent.id,
                    Question.status == QuestionStatus.OPEN,
                    (Question.priority.in_([QuestionPriority.CRITICAL, QuestionPriority.HIGH]) | (Question.impact_score >= 70)),
                )
                .order_by(Question.impact_score.desc(), Question.created_at, Question.id)
            )
        )
        manifest = {
            "intent": [str(intent.id)],
            "requirements": [str(row.id) for row in requirements],
            "research": [str(row.id) for row in evidence],
            "design_laws": [str(row.id) for row in laws],
            "questions": [str(row.id) for row in questions],
        }
        context = {
            "project_context": {"project_id": str(project.id), "name": project.name, "description": project.description or ""},
            "intent_revision_id": str(intent.id),
            "direction_id": str(direction.id),
            "intent": {
                "raw_request": intent.raw_request,
                "project_type": intent.project_type,
                "business_or_product_goal": intent.business_or_product_goal,
                "primary_audience": intent.primary_audience,
                "secondary_audience": intent.secondary_audience,
                "primary_user_tasks": intent.primary_user_tasks or [],
                "desired_user_action": intent.desired_user_action,
                "required_pages": intent.required_pages or [],
                "required_features": intent.required_features or [],
                "content_requirements": intent.content_requirements or [],
                "brand_requirements": intent.brand_requirements or [],
                "visual_preferences": intent.visual_preferences or [],
                "functional_requirements": intent.functional_requirements or [],
                "technical_requirements": intent.technical_requirements or [],
                "accessibility_requirements": intent.accessibility_requirements or [],
                "performance_requirements": intent.performance_requirements or [],
                "constraints": intent.constraints or [],
                "completeness": intent.completeness,
                "provenance": intent.provenance or {},
            },
            "direction": {
                "id": str(direction.id),
                "name": direction.name,
                "description": direction.description,
                "visual_language": direction.visual_language or {},
                "layout_direction": direction.layout_direction,
                "navigation_direction": direction.navigation_direction,
                "component_direction": direction.component_direction,
                "strengths": direction.strengths or [],
                "tradeoffs": direction.tradeoffs or [],
                "risks": direction.risks or [],
                "confidence": direction.confidence,
            },
            "requirements": [
                {"id": str(row.id), "requirement": row.requirement, "category": row.category.value, "priority": row.priority,
                 "source": row.source.value, "status": row.status.value, "rationale": row.rationale, "provenance": row.provenance or {}}
                for row in requirements
            ],
            "research": [
                {"id": str(row.id), "title": row.title, "claim": row.claim, "evidence": row.evidence,
                 "source_name": row.source_name, "source_url": row.source_url, "trust": row.trust.value,
                 "confidence": row.confidence, "provenance": row.provenance or {}}
                for row in evidence
            ],
            "design_laws": [{"id": str(row.id), "title": row.title, "rule": row.rule} for row in laws],
            "open_questions": [
                {"id": str(row.id), "question": row.question, "priority": row.priority.value,
                 "impact_score": row.impact_score, "intent_field": row.intent_field, "reason": row.reason}
                for row in questions
            ],
            "source_manifest": manifest,
        }
        return DesignReasoningContextRead.model_validate(context, strict=True).model_dump(mode="json")
