"""Design requirements with explicit source distinction and provenance."""
import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Float, JSON, String, Text, Uuid, func, ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class RequirementCategory(str, Enum):
    FUNCTIONAL="functional"; UX="UX"; VISUAL="visual"; CONTENT="content"; TECHNICAL="technical"
    ACCESSIBILITY="accessibility"; PERFORMANCE="performance"; BUSINESS="business"; BRAND="brand"; RESPONSIVE="responsive"
class RequirementSource(str, Enum): USER="user"; INFERRED="inferred"; RESEARCH="research"; SYSTEM="system"
class RequirementStatus(str, Enum): PROPOSED="proposed"; APPROVED="approved"; REJECTED="rejected"; SUPERSEDED="superseded"
def _values(items): return [item.value for item in items]

class DesignRequirement(Base):
    __tablename__ = "design_requirements"
    __table_args__ = (ForeignKeyConstraint(["project_id", "intent_id"], ["project_intents.project_id", "project_intents.id"], name="fk_design_requirements_intent_revision"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    intent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("project_intents.id", ondelete="SET NULL"), index=True)
    requirement: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[RequirementCategory] = mapped_column(SAEnum(RequirementCategory, name="requirement_category", values_callable=_values), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    source: Mapped[RequirementSource] = mapped_column(SAEnum(RequirementSource, name="requirement_source", values_callable=_values), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RequirementStatus] = mapped_column(SAEnum(RequirementStatus, name="requirement_status", values_callable=_values), nullable=False, default=RequirementStatus.PROPOSED)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    provenance: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
