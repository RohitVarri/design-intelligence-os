"""Rule-based intent extraction; replaceable through the IntentExtractor protocol."""
import re
import uuid
from datetime import datetime, timezone
from typing import Protocol
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.intent import IntentStatus, ProjectIntent
from app.models.project import Project
from app.models.question import Question, QuestionStatus
from app.schemas.intent import IntentCreate, IntentUpdate

REQUIRED_COMPLETENESS_FIELDS = ("raw_request", "project_type", "business_or_product_goal", "primary_audience", "desired_user_action", "platform")
BLOCKING_FIELDS = ("project_type", "business_or_product_goal", "primary_audience", "desired_user_action")
LIST_FIELDS = {"primary_user_tasks", "target_devices", "required_pages", "required_features", "content_requirements", "brand_requirements", "visual_preferences", "functional_requirements", "technical_requirements", "accessibility_requirements", "performance_requirements", "constraints", "references", "competitors", "success_criteria"}

class IntentExtractor(Protocol):
    """Provider boundary for later LLM-based extractors."""
    def extract(self, raw_request: str) -> tuple[dict, dict[str, float]]: ...

class RuleBasedIntentExtractor:
    """Conservative deterministic extractor: only fills fields supported by explicit terms."""
    COLORS = ("black", "white", "cream", "ivory", "gold", "champagne gold", "champagne-gold", "silver", "navy", "blue", "green", "red", "pink", "purple", "brown")
    VISUAL = ("luxury", "cinematic", "minimal", "minimalist", "editorial", "playful", "bold", "modern", "premium", "vintage", "clean", "dramatic", "soft", "elegant")

    def extract(self, raw_request: str) -> tuple[dict, dict[str, float]]:
        text = raw_request.strip()
        low = text.casefold()
        result: dict = {}
        confidence: dict[str, float] = {}
        def put(key: str, value, score: float = 0.95) -> None:
            if value is not None and value != []:
                result[key] = value
                confidence[key] = score
        if "landing page" in low:
            put("project_type", "landing page", 0.99)
        elif any(term in low for term in ("e-commerce", "ecommerce", "online store", "shopify", "checkout")):
            put("project_type", "ecommerce website", 0.99)
        elif "website" in low and any(term in low for term in ("purchase", "buy", "buying", "add to cart")):
            put("project_type", "ecommerce website", 0.72)
        elif any(term in low for term in ("web app", "web application", "dashboard")):
            put("project_type", "web application", 0.95)
        elif any(term in low for term in ("website", "web site", "site")):
            put("project_type", "website", 0.9)
        elif "mobile app" in low or "mobile application" in low:
            put("project_type", "mobile application", 0.95)
        if any(term in low for term in ("website", "web site", "landing page", "web app", "web application", "dashboard")):
            put("platform", "web", 0.9)
        elif "mobile app" in low or "mobile application" in low:
            put("platform", "mobile", 0.95)

        if re.search(r"\bdiscover\b.*\bpurchase\b|\bpurchase\b.*\bdiscover\b", low):
            put("business_or_product_goal", "Brand or product discovery and purchase", 0.95)
            put("desired_user_action", "Discover the product, evaluate it, then purchase", 0.95)
            put("primary_user_tasks", ["discover the product", "evaluate the product", "purchase the product"], 0.95)
            put("required_features", ["product discovery", "product evaluation", "purchase flow"], 0.72)
        elif re.search(r"\b(book|schedule|reserve)\b", low):
            verb = re.search(r"\b(book|schedule|reserve)\b", low).group(1)
            put("desired_user_action", f"{verb.capitalize()} a service", 0.8)
            put("primary_user_tasks", [f"{verb} a service"], 0.75)
        elif "sign up" in low or "sign-up" in low or "signup" in low:
            put("desired_user_action", "Sign up", 0.88)
            put("required_features", ["sign-up flow"], 0.85)
        elif "contact" in low or "get in touch" in low:
            put("desired_user_action", "Contact the organization", 0.82)

        if "fragrance" in low:
            put("industry", "fragrance", 0.95)
            if re.search(r"\bfor\s+(?:luxury\s+)?fragrance\s+(?:consumers|customers|enthusiasts)\b", low):
                put("primary_audience", "Luxury fragrance consumers" if "luxury" in low else "Fragrance consumers", 0.96)
            elif "luxury" in low:
                put("primary_audience", "Luxury fragrance consumers", 0.66)
            else:
                put("primary_audience", "Fragrance consumers", 0.62)
        elif "saas" in low or "software as a service" in low:
            put("industry", "software", 0.9)
            match = re.search(r"for\s+(?:my\s+)?(saas|software)(?:\s+(?:company|product|business))?", low)
            if match and "project_type" not in result:
                put("project_type", "SaaS website", 0.7)
        elif "restaurant" in low or "food" in low:
            put("industry", "food and hospitality", 0.8)
        elif "health" in low or "medical" in low:
            put("industry", "healthcare", 0.8)

        brand = re.search(r"\bfor\s+([A-Z][A-Z0-9&-]{1,29})\b", text)
        if brand and brand.group(1).casefold() not in {"my", "saas", "api", "ai"}:
            put("brand_requirements", [f"Brand name: {brand.group(1)}"], 0.99)
        found_colors = [term for term in self.COLORS if term in low]
        found_visual = [term for term in self.VISUAL if term in low]
        visual = list(dict.fromkeys(found_visual + found_colors))
        if visual:
            put("visual_preferences", visual, 0.96)
        if re.search(r"\b(accessible|accessibility|WCAG|screen reader|keyboard navigation)\b", text, re.I):
            put("accessibility_requirements", [text[m.start():m.end()] for m in re.finditer(r"\b(?:accessible|accessibility|WCAG|screen reader|keyboard navigation)\b", text, re.I)], 0.94)
        if re.search(r"\b(fast|performance|Core Web Vitals|load quickly)\b", text, re.I):
            put("performance_requirements", ["Performance matters"], 0.85)
        for page in ("home", "homepage", "product", "pricing", "about", "contact", "checkout", "FAQ"):
            if re.search(rf"\b{re.escape(page)}\b", text, re.I):
                put("required_pages", list(result.get("required_pages", [])) + [page.title()], 0.92)
        return result, confidence

class IntentExtractionService:
    """Orchestrates extraction, provenance, deterministic completeness, and lifecycle state."""
    def __init__(self, extractor: IntentExtractor | None = None):
        self.extractor = extractor or RuleBasedIntentExtractor()

    @staticmethod
    def missing_information(intent: ProjectIntent) -> list[str]:
        labels = {"project_type": "project type", "business_or_product_goal": "business or product goal", "primary_audience": "primary audience", "desired_user_action": "desired user action"}
        sources = (intent.provenance or {}).get("field_sources", {})
        return [label for field, label in labels.items() if not getattr(intent, field) or sources.get(field, {}).get("source_type") == "inferred"]

    @staticmethod
    def refresh_metrics(intent: ProjectIntent) -> None:
        sources = (intent.provenance or {}).get("field_sources", {})
        known = sum(1 for field in REQUIRED_COMPLETENESS_FIELDS if getattr(intent, field, None) and (field == "raw_request" or sources.get(field, {}).get("source_type") != "inferred"))
        intent.completeness = round(known / len(REQUIRED_COMPLETENESS_FIELDS), 3)
        sources = intent.provenance.get("field_sources", {}) if intent.provenance else {}
        scores = [info.get("confidence", 0.0) for key, info in sources.items() if key != "raw_request" and getattr(intent, key, None)]
        intent.confidence = round(sum(scores) / len(scores), 3) if scores else 0.0
        if intent.status not in (IntentStatus.APPROVED, IntentStatus.RESEARCHED, IntentStatus.READY_FOR_DIRECTION):
            intent.status = IntentStatus.NEEDS_QUESTIONS if IntentExtractionService.missing_information(intent) else IntentStatus.READY_FOR_RESEARCH

    def apply_extraction(self, intent: ProjectIntent) -> ProjectIntent:
        values, scores = self.extractor.extract(intent.raw_request)
        sources = dict((intent.provenance or {}).get("field_sources", {}))
        for field, value in values.items():
            existing = getattr(intent, field)
            empty = existing is None or existing == []
            if empty:
                setattr(intent, field, value)
                score = scores.get(field, 0.5)
                sources[field] = {"source_type": "user_request" if score >= 0.9 else "inferred", "source_id": str(intent.id), "source_reference": "raw_request", "created_by": "deterministic_extractor", "confidence": score}
        intent.provenance = {**(intent.provenance or {}), "field_sources": sources}
        self.refresh_metrics(intent)
        return intent

    def create(self, db: Session, project_id: uuid.UUID, data: IntentCreate) -> ProjectIntent:
        if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
        old_intents = db.scalars(select(ProjectIntent).where(ProjectIntent.project_id == project_id)).all()
        if old_intents:
            old_ids = [item.id for item in old_intents]
            stale = db.scalars(select(Question).where(Question.intent_id.in_(old_ids), Question.status == QuestionStatus.OPEN)).all()
            for question in stale: question.status = QuestionStatus.SUPERSEDED
        intent_id = uuid.uuid4()
        stamp = datetime.now(timezone.utc).isoformat()
        intent = ProjectIntent(id=intent_id, project_id=project_id, raw_request=data.raw_request.strip(), status=IntentStatus.DRAFT,
            provenance={"source_type": "user_request", "source_id": str(intent_id), "source_reference": "raw_request", "created_by": "user", "created_at": stamp,
                "field_sources": {"raw_request": {"source_type": "user_request", "source_id": str(intent_id), "source_reference": "raw_request", "created_by": "user", "confidence": 1.0}}})
        db.add(intent); db.flush()
        return self.apply_extraction(intent)

    @staticmethod
    def latest(db: Session, project_id: uuid.UUID) -> ProjectIntent:
        intent = db.scalar(select(ProjectIntent).where(ProjectIntent.project_id == project_id).order_by(ProjectIntent.created_at.desc(), ProjectIntent.id.desc()).limit(1))
        if not intent: raise HTTPException(404, "Project intent not found")
        return intent

    def update(self, db: Session, project_id: uuid.UUID, data: IntentUpdate) -> ProjectIntent:
        intent = self.latest(db, project_id)
        for field, value in data.model_dump(exclude_unset=True, exclude={"status"}).items():
            if value is None: continue
            setattr(intent, field, value)
            intent.provenance = dict(intent.provenance or {})
            sources = dict(intent.provenance.get("field_sources", {}))
            sources[field] = {"source_type": "user_request", "source_id": str(intent.id), "source_reference": "intent_update", "created_by": "user", "confidence": 1.0}
            intent.provenance["field_sources"] = sources
            pending = db.scalars(select(Question).where(Question.intent_id == intent.id, Question.intent_field == field, Question.status == QuestionStatus.OPEN)).all()
            for question in pending:
                question.answer = value
                question.status = QuestionStatus.ANSWERED
                question.answered_at = datetime.now(timezone.utc)
        if data.status is not None:
            intent.status = data.status
        self.refresh_metrics(intent)
        db.flush()
        return intent

    def analyze(self, db: Session, project_id: uuid.UUID) -> ProjectIntent:
        intent = self.latest(db, project_id)
        self.apply_extraction(intent)
        db.flush()
        return intent

intent_extraction = IntentExtractionService()
