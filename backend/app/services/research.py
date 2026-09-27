"""Deterministic research planning and provider boundary; no network research is performed."""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.intent import ProjectIntent
from app.models.project import Project
from app.models.research_evidence import ResearchEvidence, EvidenceTrust
from app.models.research_plan import ResearchPlan, ResearchPlanStatus
from app.models.research_query import ResearchQuery, ResearchQueryPriority
from app.schemas.research import ResearchEvidenceCreate
from app.services.intent import IntentExtractionService

@dataclass(frozen=True)
class EvidenceCandidate:
    """Common provider result shape for future search integrations."""
    title: str
    claim: str
    source_url: str | None
    source_name: str | None
    evidence: str

class ResearchProvider(Protocol):
    """Future provider contract. This build deliberately includes no live implementation."""
    def search(self, query: str) -> list[EvidenceCandidate]: ...

class ResearchService:
    def create_plan(self, db: Session, project_id: uuid.UUID) -> ResearchPlan:
        if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
        intent = IntentExtractionService.latest(db, project_id)
        plan = ResearchPlan(project_id=project_id, intent_id=intent.id, status=ResearchPlanStatus.DRAFT)
        db.add(plan); db.flush()
        product = intent.project_type or "digital product"
        audience = intent.primary_audience or "the intended audience"
        industry = intent.industry or "the relevant industry"
        luxury = "luxury" in " ".join(intent.visual_preferences).casefold() or industry.casefold() in {"fragrance", "fashion", "beauty"}
        commerce = any(word in product.casefold() for word in ("ecommerce", "e-commerce", "store")) or any("purchase" in f.casefold() for f in intent.required_features)
        entries = [
            ("Audience needs and decision journey", f"What needs and decision steps are common for {audience}?", "Clarifies the audience's information needs and the order they need to resolve them.", ResearchQueryPriority.HIGH),
            ("Information architecture", f"Which navigation and information-architecture patterns serve {product} users?", "Can inform page grouping and navigation without prescribing a visual style.", ResearchQueryPriority.HIGH),
            ("Content and product storytelling", f"What content structures help users understand {industry} offerings?", "Supports content planning and the stated product goal.", ResearchQueryPriority.MEDIUM),
            ("Accessibility", f"Which accessibility considerations apply to a {product}?", "Surfaces accessibility requirements for later human review.", ResearchQueryPriority.HIGH),
            ("Responsive behavior", f"What responsive UX considerations matter for a {product}?", "Informs layouts across devices when responsive web delivery is intended.", ResearchQueryPriority.MEDIUM),
            ("Performance", f"What performance considerations affect a {product} experience?", "Highlights potential performance constraints for later technical planning.", ResearchQueryPriority.MEDIUM),
        ]
        if commerce:
            entries.extend([
                ("Product discovery", f"How do users discover and compare products in {industry} ecommerce?", "Informs product discovery and comparison flows.", ResearchQueryPriority.HIGH),
                ("Checkout usability", "Which checkout patterns reduce friction while keeping user control clear?", "Checkout directly affects the stated purchase flow.", ResearchQueryPriority.HIGH),
            ])
        if luxury:
            entries.extend([
                ("Luxury commerce experience", f"What UX conventions and tradeoffs appear in luxury {industry} commerce?", "Provides reference evidence while leaving direction choice to the user.", ResearchQueryPriority.MEDIUM),
                ("Premium typography and imagery", f"How do premium {industry} brands balance typography, imagery, and legibility?", "Explores visual approaches and tradeoffs; does not turn trends into requirements.", ResearchQueryPriority.MEDIUM),
            ])
        if intent.competitors:
            entries.append(("Competitor patterns", f"Review user-specified competitors: {', '.join(intent.competitors)}", "Compares the user-named references only.", ResearchQueryPriority.MEDIUM))
        elif commerce:
            entries.append(("Comparable commerce patterns", f"What product-discovery patterns are used by relevant {industry} commerce sites?", "Provides category context without inventing named competitors.", ResearchQueryPriority.LOW))
        for area, query, reason, priority in entries:
            db.add(ResearchQuery(plan_id=plan.id, research_area=area, query=query, reason=reason, priority=priority))
        db.flush()
        return plan

    def get_latest_plan(self, db: Session, project_id: uuid.UUID) -> ResearchPlan:
        if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
        plan = db.scalar(select(ResearchPlan).where(ResearchPlan.project_id == project_id).order_by(ResearchPlan.created_at.desc(), ResearchPlan.id.desc()).limit(1))
        if not plan: raise HTTPException(404, "Research plan not found")
        return plan

    def list_evidence(self, db: Session, project_id: uuid.UUID) -> list[ResearchEvidence]:
        if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
        return list(db.scalars(select(ResearchEvidence).where(ResearchEvidence.project_id == project_id).order_by(ResearchEvidence.created_at.desc())))

    def store_evidence(self, db: Session, project_id: uuid.UUID, data: ResearchEvidenceCreate) -> ResearchEvidence:
        if not db.get(Project, project_id): raise HTTPException(404, "Project not found")
        intent = IntentExtractionService.latest(db, project_id)
        evidence_id = uuid.uuid4()
        provenance = {"source_type": "user_provided_research", "source_id": str(evidence_id), "source_reference": data.source_url or data.source_name or "user_submitted_evidence", "created_by": "user", "created_at": datetime.now(timezone.utc).isoformat()}
        provenance["trust_reason"] = "External and user-submitted evidence is untrusted until server verification or human review."
        obj = ResearchEvidence(id=evidence_id, project_id=project_id, intent_id=intent.id, trust=EvidenceTrust.UNTRUSTED,
            provenance=provenance, **data.model_dump())
        db.add(obj); db.flush(); return obj

    def review_evidence(self, db: Session, project_id: uuid.UUID, evidence_id: uuid.UUID, *, eligible: bool, rationale: str, reviewer_id: str) -> ResearchEvidence:
        """Apply an auditable human trust transition; request payload cannot set trust directly."""
        row = db.scalar(select(ResearchEvidence).where(ResearchEvidence.project_id == project_id, ResearchEvidence.id == evidence_id))
        if not row: raise HTTPException(404, "Research evidence not found")
        row.trust = EvidenceTrust.REVIEWED if eligible else EvidenceTrust.UNTRUSTED
        row.provenance = {**(row.provenance or {}), "review": {"reviewer_id": reviewer_id, "eligible": eligible, "rationale": rationale, "reviewed_at": datetime.now(timezone.utc).isoformat()}}
        db.flush()
        return row

research_service = ResearchService()
