"""Persisted design-plan proposals and human-approved plans."""
import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    Float,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    JSON,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DesignPlanStatus(str, Enum):
    PROPOSED = "proposed"
    PREVIEWED = "previewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


def _values(items):
    return [item.value for item in items]


class DesignPlan(Base):
    """An immutable-revision plan candidate tied to exact intent and direction records."""

    __tablename__ = "design_plans"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_design_plan_confidence_range"),
        ForeignKeyConstraint(
            ["project_id", "intent_id"],
            ["project_intents.project_id", "project_intents.id"],
            name="fk_design_plans_intent_revision",
        ),
        ForeignKeyConstraint(
            ["project_id", "direction_id"],
            ["design_directions.project_id", "design_directions.id"],
            name="fk_design_plans_direction_project",
        ),
        UniqueConstraint("candidate_id", name="uq_design_plan_candidate"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    intent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("project_intents.id", ondelete="RESTRICT"), nullable=False, index=True)
    direction_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("design_directions.id", ondelete="RESTRICT"), nullable=False, index=True)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("ai_output_candidates.id", ondelete="SET NULL"), index=True)
    status: Mapped[DesignPlanStatus] = mapped_column(
        SAEnum(DesignPlanStatus, name="design_plan_status", values_callable=_values),
        nullable=False,
        default=DesignPlanStatus.PROPOSED,
    )
    plan: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    provenance: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(200))
