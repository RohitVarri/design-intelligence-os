"""Design-direction proposals, separate assessments, and explicit human selection."""
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.decision import DecisionSource
from app.models.direction import DesignDirection, DirectionStatus
from app.models.direction_assessment import DesignDirectionAssessment
from app.models.design_state import DesignState
from app.models.intent import IntentStatus, ProjectIntent
from app.models.memory import MemoryTrust
from app.models.project import Project
from app.models.research_evidence import EvidenceTrust, ResearchEvidence
from app.models.question import Question, QuestionPriority, QuestionStatus
from app.schemas.decision import DecisionCreate
from app.schemas.direction import DirectionAssessmentCreate, DirectionCreate, DirectionStatusUpdate
from app.schemas.memory import MemoryCreate
from app.services.design_state import create_initial_design_state, update_design_state
from app.services.decisions import record_decision
from app.services.intent import IntentExtractionService
from app.services.memory import store_memory
from app.services.operations import operation_service

class DirectionService:
    def create(self, db: Session, project_id: uuid.UUID, data: DirectionCreate) -> list[DesignDirection]:
        if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
        intent = IntentExtractionService.latest(db, project_id)
        if data.generate:
            return self.generate(db, project_id, intent)
        fields = data.model_dump(exclude={"generate", "name", "description", "confidence", "supporting_research_ids"})
        ids = [str(value) for value in data.supporting_research_ids]
        if ids:
            found = set(db.scalars(select(ResearchEvidence.id).where(ResearchEvidence.project_id == project_id, ResearchEvidence.id.in_(data.supporting_research_ids))))
            if len(found) != len(set(data.supporting_research_ids)):
                raise HTTPException(422, "Every supporting research ID must belong to this project")
        direction = DesignDirection(project_id=project_id, intent_id=intent.id, name=data.name or "Untitled direction",
            description=data.description or "A user-provided strategic design hypothesis.", confidence=data.confidence,
            supporting_research_ids=ids,
            provenance={"source_type": "user_direction_submission", "source_id": None, "source_reference": "POST /projects/{project_id}/directions", "created_by": "user", "created_at": datetime.now(timezone.utc).isoformat()}, **fields)
        db.add(direction); db.flush(); return [direction]

    def generate(self, db: Session, project_id: uuid.UUID, intent: ProjectIntent | None = None) -> list[DesignDirection]:
        intent = intent or IntentExtractionService.latest(db, project_id)
        missing = IntentExtractionService.missing_information(intent)
        if missing:
            raise HTTPException(409, "Resolve or explicitly confirm these high-impact intent fields before generating directions: " + ", ".join(missing))
        pending = db.scalars(select(Question).where(Question.project_id == project_id, Question.intent_id == intent.id, Question.status == QuestionStatus.OPEN, Question.priority.in_([QuestionPriority.CRITICAL, QuestionPriority.HIGH]))).all()
        if pending:
            raise HTTPException(409, "Answer or skip high-impact questions before generating directions")
        product = intent.project_type or "digital experience"
        is_commerce = any(term in product.casefold() for term in ("commerce", "ecommerce", "e-commerce", "store")) or any("purchase" in f.casefold() for f in intent.required_features)
        lux = "luxury" in " ".join(intent.visual_preferences).casefold() or intent.industry in {"fragrance", "fashion", "beauty"}
        templates = ([
            {"name":"Editorial Luxury", "description":"A story-led direction that foregrounds product meaning and a considered editorial rhythm.", "typography_direction":"Expressive display typography paired with a highly legible text face.", "color_direction":"Use the user's stated palette as a constraint; keep contrast and product clarity visible.", "layout_direction":"Editorial compositions with deliberate pacing and clear product wayfinding.", "navigation_direction":"Quiet primary navigation with discoverable product categories.", "imagery_direction":"Large, art-directed product imagery balanced with descriptive details.", "motion_direction":"Restrained transitions that preserve reading and interaction clarity.", "density":"low-to-medium", "emotional_tone":["considered","distinctive"], "strengths":["Makes room for brand storytelling", "Supports an intentional browsing pace"], "tradeoffs":["Can increase the distance to product comparison"], "risks":["Story sections could obscure key product details if hierarchy is weak"]},
            {"name":"Cinematic Minimal", "description":"A sparse, image-led hypothesis with a focused conversion path and a strong sense of atmosphere.", "typography_direction":"Confident, restrained typography with accessible sizing.", "color_direction":"A limited palette drawn from explicit user preferences, subject to contrast checks.", "layout_direction":"Full-width image moments separated by compact, clearly grouped information.", "navigation_direction":"Minimal global navigation with persistent access to core tasks.", "imagery_direction":"Cinematic crops paired with real product information and alternate views.", "motion_direction":"Subtle entrance and state transitions; all motion remains optional and nonessential.", "density":"low", "emotional_tone":["atmospheric","focused"], "strengths":["Creates a memorable visual entry point", "Keeps the number of competing elements low"], "tradeoffs":["A sparse layout may hide comparison or support content"], "risks":["Image-heavy sections need performance and accessibility review"]},
            {"name":"Modern Premium Commerce", "description":"A product-first direction that pairs a premium visual tone with direct discovery, comparison, and purchase tasks.", "typography_direction":"Clear hierarchy optimized for scanning product names, options, and prices.", "color_direction":"A refined palette with reserved accents and verified text contrast.", "layout_direction":"Structured product grids and comparison-ready detail views.", "navigation_direction":"Visible categories, search, and a clear cart entry point.", "imagery_direction":"Consistent product photography with details that support evaluation.", "motion_direction":"Fast, purposeful feedback for filters, variants, and cart actions.", "density":"medium", "emotional_tone":["confident","useful"], "strengths":["Keeps product tasks easy to find", "Supports comparison and purchase flow"], "tradeoffs":["Commerce conventions may feel less distinctive"], "risks":["Product density can weaken editorial storytelling"]},
        ] if is_commerce or lux else [
            {"name":"Product Clarity", "description":"A task-focused hypothesis that explains the product quickly and keeps its primary action visible.", "typography_direction":"Plain, strong hierarchy designed for fast scanning.", "color_direction":"A compact palette; use only explicitly supplied brand colors as fixed choices.", "layout_direction":"Clear sections that connect problem, value, evidence, and next action.", "navigation_direction":"A small set of task-centered destinations.", "imagery_direction":"Product interface imagery with context and explanatory labels.", "motion_direction":"Functional feedback only; transitions are never required to understand content.", "density":"medium", "emotional_tone":["clear","confident"], "strengths":["Supports quick comprehension", "Keeps a clear path to the primary action"], "tradeoffs":["Can feel conventional without distinctive brand content"], "risks":["Over-compression can omit nuance"]},
            {"name":"Editorial Product Story", "description":"A narrative-led direction that introduces the product through user needs, proof, and carefully paced content.", "typography_direction":"Editorial headings supported by readable body text.", "color_direction":"An expressive but controlled palette pending explicit brand guidance.", "layout_direction":"Sequential storytelling sections with repeated routes back to the main task.", "navigation_direction":"Compact navigation with clear section signposts.", "imagery_direction":"Contextual imagery and product details rather than decorative-only visuals.", "motion_direction":"Optional progressive reveals that do not delay access to content.", "density":"low-to-medium", "emotional_tone":["human","considered"], "strengths":["Creates room for context and differentiation"], "tradeoffs":["Requires stronger content planning"], "risks":["Longer paths may delay task completion"]},
            {"name":"Trust-led Structured", "description":"A structured direction that surfaces evidence, product details, and support close to user decisions.", "typography_direction":"Highly legible typography with stable labels and patterns.", "color_direction":"Functional color roles, with brand accents added only when known.", "layout_direction":"Consistent cards, comparison areas, and explicit evidence placement.", "navigation_direction":"Predictable hierarchy with persistent access to key areas.", "imagery_direction":"Evidence-bearing imagery and annotated product views.", "motion_direction":"Low motion and immediate feedback.", "density":"medium", "emotional_tone":["reassuring","practical"], "strengths":["Makes decision support easy to locate"], "tradeoffs":["May feel less expressive"], "risks":["Too much supporting detail can increase density"]},
        ])
        preferences = list(intent.visual_preferences)
        requirements = list(intent.brand_requirements)
        known_constraints = list(intent.constraints)
        confidence = round(0.25 + 0.5 * intent.completeness, 3)
        stamp = datetime.now(timezone.utc).isoformat()
        research_rows = db.scalars(select(ResearchEvidence).where(ResearchEvidence.project_id == project_id, ResearchEvidence.intent_id == intent.id, ResearchEvidence.trust != EvidenceTrust.UNTRUSTED)).all()
        research_rows = [row for row in research_rows if row.relevance is None or row.relevance >= 0.5]
        research_context = [{"evidence_id": str(row.id), "title": row.title, "trust": row.trust.value} for row in research_rows]
        research_ids = [str(row.id) for row in research_rows]
        rows = []
        for item in templates:
            visual = {"hypothesis": item["name"], "explicit_user_preferences": preferences, "known_brand_requirements": requirements, "known_constraints": known_constraints, "research_context": research_context}
            row = DesignDirection(project_id=project_id, intent_id=intent.id, visual_language=visual,
                target_audience_fit=f"Audience fit remains uncertain until the primary audience is confirmed." if not intent.primary_audience else f"Consider fit for: {intent.primary_audience}.",
                supporting_research_ids=research_ids, confidence=confidence,
                provenance={"source_type":"intent_hypothesis", "source_id":str(intent.id), "source_reference":"structured_intent", "created_by":"deterministic_direction_engine", "created_at":stamp}, **item)
            db.add(row); rows.append(row)
        db.flush(); return rows

    def list_for_project(self, db: Session, project_id: uuid.UUID) -> list[DesignDirection]:
        if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
        return list(db.scalars(select(DesignDirection).where(DesignDirection.project_id == project_id).order_by(DesignDirection.created_at, DesignDirection.name)))

    def get(self, db: Session, project_id: uuid.UUID, direction_id: uuid.UUID) -> DesignDirection:
        row = db.scalar(select(DesignDirection).where(DesignDirection.project_id == project_id, DesignDirection.id == direction_id))
        if not row: raise HTTPException(404, "Design direction not found")
        return row

    def update_status(self, db: Session, project_id: uuid.UUID, direction_id: uuid.UUID, data: DirectionStatusUpdate) -> DesignDirection:
        direction = self.get(db, project_id, direction_id)
        if direction.status == DirectionStatus.SELECTED:
            raise HTTPException(409, "A selected direction can only be replaced through another explicit selection")
        direction.status = data.status
        db.flush()
        return direction

    def assess(self, db: Session, project_id: uuid.UUID, direction_id: uuid.UUID, data: DirectionAssessmentCreate) -> DesignDirectionAssessment:
        direction = self.get(db, project_id, direction_id)
        assessment = DesignDirectionAssessment(direction_id=direction.id, **data.model_dump())
        db.add(assessment); db.flush(); return assessment

    def assessments(self, db: Session, project_id: uuid.UUID, direction_id: uuid.UUID) -> list[DesignDirectionAssessment]:
        direction = self.get(db, project_id, direction_id)
        return list(db.scalars(select(DesignDirectionAssessment).where(DesignDirectionAssessment.direction_id == direction.id).order_by(DesignDirectionAssessment.created_at)))

    def select(self, db: Session, project_id: uuid.UUID, direction_id: uuid.UUID) -> DesignDirection:
        direction = self.get(db, project_id, direction_id)
        if direction.status != DirectionStatus.PROPOSED:
            raise HTTPException(409, f"Only proposed directions can be selected; current status is {direction.status.value}")
        previous = db.scalars(select(DesignDirection).where(DesignDirection.project_id == project_id, DesignDirection.status == DirectionStatus.SELECTED)).all()
        for old in previous: old.status = DirectionStatus.ARCHIVED
        direction.status = DirectionStatus.SELECTED
        intent = db.get(ProjectIntent, direction.intent_id)
        if not intent: raise HTTPException(409, "Design direction intent no longer exists")
        intent.status = IntentStatus.APPROVED
        state = db.get(DesignState, project_id)
        if state is None: state = create_initial_design_state(db, project_id)
        new_state = dict(state.state)
        new_state["direction_selection"] = {"direction_id": str(direction.id), "name": direction.name, "status": "selected"}
        update_design_state(db, project_id, new_state, f"User selected design direction: {direction.name}")
        stamp = datetime.now(timezone.utc).isoformat()
        provenance = {"source_type":"user_selection", "source_id":str(direction.id), "source_reference":"selected_design_direction", "created_by":"user", "created_at":stamp}
        record_decision(db, project_id, DecisionCreate(source=DecisionSource.USER, title=f"Selected design direction: {direction.name}", rationale=f"The user explicitly selected '{direction.name}'. {direction.description}", provenance=provenance))
        store_memory(db, project_id, MemoryCreate(category="design_direction", content=f"Selected design direction: {direction.name}. {direction.description}", trust=MemoryTrust.USER_APPROVED, provenance=provenance))
        operation_service.record_human_selection(db, project_id, direction.id, direction.name, DirectionStatus.PROPOSED.value)
        db.flush(); return direction

direction_service = DirectionService()
