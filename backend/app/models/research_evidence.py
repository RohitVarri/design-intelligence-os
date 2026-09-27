"""Research evidence with source, trust, and provenance metadata."""
import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Float, JSON, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class EvidenceSourceType(str, Enum):
    RESEARCH_PAPER="research_paper"; DESIGN_PUBLICATION="design_publication"; DESIGN_GALLERY="design_gallery"
    PATTERN_LIBRARY="pattern_library"; ACCESSIBILITY_STANDARD="accessibility_standard"; INDUSTRY_REPORT="industry_report"
    COMPETITOR="competitor"; WEBSITE="website"; DOCUMENTATION="documentation"; COMMUNITY="community"
    USER_REFERENCE="user_reference"; OTHER="other"
class TrendStage(str, Enum):
    EMERGING="emerging"; ESTABLISHED="established"; SATURATED="saturated"; DECLINING="declining"; ARCHIVED="archived"; UNKNOWN="unknown"
class EvidenceTrust(str, Enum):
    AUTHORITATIVE="authoritative"; RELIABLE="reliable"; INFORMATIONAL="informational"; EXPERIMENTAL="experimental"; UNTRUSTED="untrusted"
def _values(items): return [item.value for item in items]

class ResearchEvidence(Base):
    """A traceable research claim; evidence does not become an instruction by itself."""
    __tablename__ = "research_evidence"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    intent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("project_intents.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(String(300))
    source_type: Mapped[EvidenceSourceType] = mapped_column(SAEnum(EvidenceSourceType, name="evidence_source_type", values_callable=_values), nullable=False, default=EvidenceSourceType.OTHER)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    industry: Mapped[str | None] = mapped_column(String(200))
    audience: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    relevance: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    trend_stage: Mapped[TrendStage] = mapped_column(SAEnum(TrendStage, name="trend_stage", values_callable=_values), nullable=False, default=TrendStage.UNKNOWN)
    tags: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    related_requirement: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    trust: Mapped[EvidenceTrust] = mapped_column(SAEnum(EvidenceTrust, name="evidence_trust", values_callable=_values), nullable=False, default=EvidenceTrust.UNTRUSTED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
