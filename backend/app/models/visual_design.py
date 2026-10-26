"""Persisted BUILD 06 visual design candidates and approved specifications."""
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime, Enum as SAEnum, ForeignKey, ForeignKeyConstraint, JSON, String,
    UniqueConstraint, Uuid, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.schemas.visual_design import VisualDesignStatus


def _values(items):
    return [item.value for item in items]


class VisualDesign(Base):
    """One immutable visual proposal tied to its precise plan and wireframe."""

    __tablename__ = "visual_designs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "design_plan_id"],
            ["design_plans.project_id", "design_plans.id"],
            name="fk_visual_designs_plan_project",
        ),
        ForeignKeyConstraint(
            ["project_id", "wireframe_set_id"],
            ["wireframe_sets.project_id", "wireframe_sets.id"],
            name="fk_visual_designs_wireframe_project",
        ),
        ForeignKeyConstraint(
            ["project_id", "intent_id"],
            ["project_intents.project_id", "project_intents.id"],
            name="fk_visual_designs_intent_revision",
        ),
        ForeignKeyConstraint(
            ["project_id", "direction_id"],
            ["design_directions.project_id", "design_directions.id"],
            name="fk_visual_designs_direction_project",
        ),
        UniqueConstraint("candidate_id", name="uq_visual_design_candidate"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    intent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("project_intents.id", ondelete="RESTRICT"), nullable=False, index=True)
    direction_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("design_directions.id", ondelete="RESTRICT"), nullable=False, index=True)
    design_plan_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("design_plans.id", ondelete="RESTRICT"), nullable=False, index=True)
    wireframe_set_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("wireframe_sets.id", ondelete="RESTRICT"), nullable=False, index=True)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("ai_output_candidates.id", ondelete="SET NULL"), index=True)
    status: Mapped[VisualDesignStatus] = mapped_column(SAEnum(VisualDesignStatus, name="visual_design_status", values_callable=_values), nullable=False, default=VisualDesignStatus.PROPOSED)
    visual_design: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    provenance: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(200))
