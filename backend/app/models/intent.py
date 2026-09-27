"""Structured project intent, kept distinct from extracted guesses."""
import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import DateTime, Enum as SAEnum, Float, ForeignKey, JSON, String, Text, Uuid, func, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class IntentStatus(str, Enum):
    DRAFT = "draft"
    NEEDS_QUESTIONS = "needs_questions"
    READY_FOR_RESEARCH = "ready_for_research"
    RESEARCHED = "researched"
    READY_FOR_DIRECTION = "ready_for_direction"
    APPROVED = "approved"

def _enum_values(items):
    return [item.value for item in items]

class ProjectIntent(Base):
    """Latest or historical structured interpretation of a project's request."""
    __tablename__ = "project_intents"
    __table_args__ = (UniqueConstraint("project_id", "revision_number", name="uq_project_intent_revision"), UniqueConstraint("project_id", "id", name="uq_project_intent_project_id"),
                      CheckConstraint("revision_number >= 1", name="ck_intent_revision_positive"),
                      CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_intent_confidence_range"),
                      CheckConstraint("completeness >= 0 AND completeness <= 1", name="ck_intent_completeness_range"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(default=1, nullable=False)
    raw_request: Mapped[str] = mapped_column(Text, nullable=False)
    project_type: Mapped[str | None] = mapped_column(String(200))
    business_or_product_goal: Mapped[str | None] = mapped_column(Text)
    primary_audience: Mapped[str | None] = mapped_column(Text)
    secondary_audience: Mapped[str | None] = mapped_column(Text)
    primary_user_tasks: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    desired_user_action: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(String(200))
    platform: Mapped[str | None] = mapped_column(String(100))
    target_devices: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    required_pages: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    required_features: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    content_requirements: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    brand_requirements: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    visual_preferences: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    functional_requirements: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    technical_requirements: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    accessibility_requirements: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    performance_requirements: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    constraints: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    references: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    competitors: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    success_criteria: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    budget_or_resource_constraints: Mapped[str | None] = mapped_column(Text)
    timeline_constraints: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    completeness: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    provenance: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    status: Mapped[IntentStatus] = mapped_column(SAEnum(IntentStatus, name="intent_status", values_callable=_enum_values), nullable=False, default=IntentStatus.DRAFT)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="user")
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("project_intents.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
