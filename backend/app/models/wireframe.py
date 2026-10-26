"""Persisted wireframe candidates tied to an approved Design Plan."""
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime, Enum as SAEnum, ForeignKey, ForeignKeyConstraint, JSON, String,
    UniqueConstraint, Uuid, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.schemas.wireframe import WireframeSetStatus


def _values(items):
    return [item.value for item in items]


class WireframeSet(Base):
    """One immutable candidate set covering every page in an approved plan."""

    __tablename__ = "wireframe_sets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "design_plan_id"],
            ["design_plans.project_id", "design_plans.id"],
            name="fk_wireframe_sets_plan_project",
        ),
        ForeignKeyConstraint(
            ["project_id", "intent_id"],
            ["project_intents.project_id", "project_intents.id"],
            name="fk_wireframe_sets_intent_revision",
        ),
        ForeignKeyConstraint(
            ["project_id", "direction_id"],
            ["design_directions.project_id", "design_directions.id"],
            name="fk_wireframe_sets_direction_project",
        ),
        UniqueConstraint("candidate_id", name="uq_wireframe_set_candidate"),
        UniqueConstraint("project_id", "id", name="uq_wireframe_set_project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    design_plan_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("design_plans.id", ondelete="RESTRICT"), nullable=False, index=True)
    intent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("project_intents.id", ondelete="RESTRICT"), nullable=False, index=True)
    direction_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("design_directions.id", ondelete="RESTRICT"), nullable=False, index=True)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("ai_output_candidates.id", ondelete="SET NULL"), index=True)
    status: Mapped[WireframeSetStatus] = mapped_column(SAEnum(WireframeSetStatus, name="wireframe_set_status", values_callable=_values), nullable=False, default=WireframeSetStatus.PROPOSED)
    wireframe: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    provenance: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(200))
