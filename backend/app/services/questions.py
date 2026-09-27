"""Minimal clarification generation and deterministic impact ranking."""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.intent import ProjectIntent
from app.models.question import Question, QuestionCategory, QuestionPriority, QuestionStatus
from app.models.project import Project
from app.schemas.question import QuestionCreate
from app.services.intent import IntentExtractionService

@dataclass(frozen=True)
class QuestionCandidate:
    question: str
    category: QuestionCategory
    reason: str
    intent_field: str | None
    factors: tuple[int, int, int, int, int, int]
    required: bool = True

def calculate_impact_score(factors: tuple[int, int, int, int, int, int]) -> float:
    """Score downstream impact from dependent fields, IA, visual, technical, a11y, and conversion factors."""
    fields, architecture, visual, technical, accessibility, conversion = factors
    return float(min(100, fields * 10 + architecture * 20 + visual * 15 + technical * 15 + accessibility * 10 + conversion * 25))

def priority_for_score(score: float) -> QuestionPriority:
    if score >= 90: return QuestionPriority.CRITICAL
    if score >= 70: return QuestionPriority.HIGH
    if score >= 45: return QuestionPriority.MEDIUM
    return QuestionPriority.LOW

def score_question(category: QuestionCategory) -> tuple[float, QuestionPriority, str]:
    factors = {
        QuestionCategory.GOAL: (3, 1, 1, 0, 0, 1),
        QuestionCategory.AUDIENCE: (2, 2, 1, 0, 0, 1),
        QuestionCategory.FUNCTIONALITY: (2, 2, 0, 0, 0, 1),
        QuestionCategory.UX: (2, 2, 0, 0, 0, 1),
        QuestionCategory.PLATFORM: (2, 1, 0, 2, 1, 0),
        QuestionCategory.BRANDING: (2, 0, 2, 0, 0, 0),
        QuestionCategory.VISUAL: (2, 0, 2, 0, 0, 0),
        QuestionCategory.ACCESSIBILITY: (2, 1, 0, 0, 2, 0),
        QuestionCategory.TECHNICAL: (2, 1, 0, 2, 0, 0),
        QuestionCategory.BUSINESS: (3, 1, 1, 0, 0, 1),
        QuestionCategory.CONTENT: (1, 1, 0, 0, 0, 0),
        QuestionCategory.CONSTRAINTS: (1, 0, 0, 1, 0, 0),
        QuestionCategory.REFERENCES: (1, 0, 1, 0, 0, 0),
    }
    effects = {QuestionCategory.GOAL: "goal alignment and conversion flow", QuestionCategory.AUDIENCE: "information architecture and audience fit", QuestionCategory.FUNCTIONALITY: "page structure and user flows", QuestionCategory.UX: "navigation and user flows", QuestionCategory.PLATFORM: "technical architecture and responsive behavior", QuestionCategory.BRANDING: "brand alignment and visual direction", QuestionCategory.VISUAL: "visual direction", QuestionCategory.ACCESSIBILITY: "accessibility decisions", QuestionCategory.TECHNICAL: "technical architecture", QuestionCategory.BUSINESS: "business and conversion choices", QuestionCategory.CONTENT: "content structure", QuestionCategory.CONSTRAINTS: "scope and implementation choices", QuestionCategory.REFERENCES: "reference and differentiation choices"}
    score = calculate_impact_score(factors[category])
    return score, priority_for_score(score), effects[category]

class QuestionService:
    def _persist(self, db: Session, project_id: uuid.UUID, intent_id: uuid.UUID, data: QuestionCreate) -> Question:
        score, priority, impact = score_question(data.category)
        obj = Question(project_id=project_id, intent_id=intent_id, question=data.question, category=data.category,
            priority=priority, impact=impact, impact_score=score, reason=data.reason, intent_field=data.intent_field,
            answer_type=data.answer_type, options=data.options, required=data.required, status=QuestionStatus.OPEN)
        db.add(obj); db.flush(); return obj

    def generate(self, db: Session, project_id: uuid.UUID, intent: ProjectIntent) -> list[Question]:
        candidates: list[QuestionCandidate] = []
        field_sources = (intent.provenance or {}).get("field_sources", {})
        if not intent.desired_user_action:
            candidates.append(QuestionCandidate("What should the primary user do after visiting this experience?", QuestionCategory.GOAL, "The primary action determines the main flow, calls to action, and success criteria.", "desired_user_action", (3,1,1,0,0,1)))
        elif not intent.business_or_product_goal:
            candidates.append(QuestionCandidate("What business or product outcome should the experience support?", QuestionCategory.BUSINESS, "The broader outcome shapes success criteria and how the primary action is framed.", "business_or_product_goal", (3,1,1,0,0,1)))
        if not intent.project_type or field_sources.get("project_type", {}).get("source_type") == "inferred":
            project_question = "Should this be a direct ecommerce experience, or should purchase happen through another service?" if intent.project_type and "commerce" in intent.project_type.casefold() else f"The request suggests a {intent.project_type or 'digital experience'}. Is that the right project type?"
            candidates.append(QuestionCandidate(project_question, QuestionCategory.FUNCTIONALITY, "Project type changes information architecture, key user flows, and implementation scope.", "project_type", (2,2,0,2,0,1)))
        if not intent.primary_audience or field_sources.get("primary_audience", {}).get("source_type") == "inferred":
            audience_question = f"The request suggests {intent.primary_audience}. Is that the intended primary audience, or should it target someone else?" if intent.primary_audience else "Who is the primary audience, and what do they need to accomplish?"
            candidates.append(QuestionCandidate(audience_question, QuestionCategory.AUDIENCE, "Audience needs can materially change content hierarchy, navigation, and interaction patterns.", "primary_audience", (2,2,1,0,0,1)))
        if intent.project_type and (not intent.required_features or field_sources.get("required_features", {}).get("source_type") == "inferred"):
            question_text = f"The request suggests these features: {', '.join(intent.required_features)}. Are these required, or should they change?" if intent.required_features else "Which essential features or actions must the first version support?"
            candidates.append(QuestionCandidate(question_text, QuestionCategory.FUNCTIONALITY, "Essential capabilities determine page structure and user flows.", "required_features", (2,2,0,0,0,1)))
        if not intent.brand_requirements and not intent.visual_preferences:
            candidates.append(QuestionCandidate("Is there an existing brand identity or visual constraint the design should follow?", QuestionCategory.BRANDING, "Existing brand assets or constraints can change every proposed visual direction.", "brand_requirements", (2,0,2,0,0,0)))
        existing = set(db.scalars(select(Question.question).where(Question.project_id == project_id, Question.intent_id == intent.id, Question.status == QuestionStatus.OPEN)))
        candidates = sorted((candidate for candidate in candidates if candidate.question not in existing), key=lambda item: calculate_impact_score(item.factors), reverse=True)
        return [self._persist(db, project_id, intent.id, QuestionCreate(question=item.question, category=item.category, reason=item.reason, intent_field=item.intent_field)) for item in candidates[:4]]

    def create(self, db: Session, project_id: uuid.UUID, data: QuestionCreate) -> Question:
        if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
        intent = IntentExtractionService.latest(db, project_id)
        return self._persist(db, project_id, intent.id, data)

    def list_for_project(self, db: Session, project_id: uuid.UUID, open_only: bool = False) -> list[Question]:
        if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
        stmt = select(Question).where(Question.project_id == project_id)
        if open_only: stmt = stmt.where(Question.status == QuestionStatus.OPEN)
        return list(db.scalars(stmt.order_by(Question.impact_score.desc(), Question.created_at)))

    def get(self, db: Session, project_id: uuid.UUID, question_id: uuid.UUID) -> Question:
        obj = db.scalar(select(Question).where(Question.project_id == project_id, Question.id == question_id))
        if not obj: raise HTTPException(404, "Question not found")
        return obj

    def answer(self, db: Session, project_id: uuid.UUID, question_id: uuid.UUID, answer) -> Question:
        obj = self.get(db, project_id, question_id)
        if obj.status != QuestionStatus.OPEN: raise HTTPException(409, "Only open questions can be answered")
        if obj.answer_type == "text" and not isinstance(answer, str): raise HTTPException(422, "This question expects a text answer")
        if obj.answer_type == "single_choice" and (not isinstance(answer, str) or (obj.options and answer not in obj.options)):
            raise HTTPException(422, "Answer must be one of the question's options")
        if obj.answer_type == "multi_choice" and (not isinstance(answer, list) or not all(isinstance(item, str) for item in answer)):
            raise HTTPException(422, "This question expects a list of text choices")
        if obj.answer_type == "boolean" and not isinstance(answer, bool): raise HTTPException(422, "This question expects a true or false answer")
        if obj.answer_type == "number" and (isinstance(answer, bool) or not isinstance(answer, (int, float))): raise HTTPException(422, "This question expects a numeric answer")
        obj.answer = answer
        obj.status = QuestionStatus.ANSWERED
        obj.answered_at = datetime.now(timezone.utc)
        if obj.intent_field:
            intent = IntentExtractionService.latest(db, project_id)
            if intent.id != obj.intent_id: raise HTTPException(409, "Question belongs to a superseded intent")
            value = answer
            valid_fields = {"project_type", "business_or_product_goal", "primary_audience", "secondary_audience", "primary_user_tasks", "desired_user_action", "industry", "platform", "target_devices", "required_pages", "required_features", "content_requirements", "brand_requirements", "visual_preferences", "functional_requirements", "technical_requirements", "accessibility_requirements", "performance_requirements", "constraints", "references", "competitors", "success_criteria", "budget_or_resource_constraints", "timeline_constraints"}
            if obj.intent_field not in valid_fields:
                raise HTTPException(422, "Question target is not an editable intent field")
            if isinstance(value, str) and obj.intent_field in {"primary_user_tasks", "target_devices", "required_pages", "required_features", "content_requirements", "brand_requirements", "visual_preferences", "functional_requirements", "technical_requirements", "accessibility_requirements", "performance_requirements", "constraints", "references", "competitors", "success_criteria"}:
                value = [item.strip() for item in value.split(",") if item.strip()]
            setattr(intent, obj.intent_field, value)
            intent.provenance = dict(intent.provenance or {})
            sources = dict(intent.provenance.get("field_sources", {}))
            sources[obj.intent_field] = {"source_type": "user_answer", "source_id": str(obj.id), "source_reference": "question_answer", "created_by": "user", "confidence": 1.0}
            intent.provenance["field_sources"] = sources
            IntentExtractionService.refresh_metrics(intent)
        db.flush()
        return obj

    def update(self, db: Session, project_id: uuid.UUID, question_id: uuid.UUID, *, status=None, reason=None) -> Question:
        obj = self.get(db, project_id, question_id)
        if status == QuestionStatus.ANSWERED: raise HTTPException(422, "Use the answer endpoint to answer a question")
        if status is not None: obj.status = status
        if reason is not None: obj.reason = reason
        db.flush(); return obj

question_service = QuestionService()
