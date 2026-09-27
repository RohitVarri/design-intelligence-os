"""Strategic design direction hypotheses, not rendered designs."""
import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Float, JSON, String, Text, Uuid, func, ForeignKeyConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class DirectionStatus(str, Enum): PROPOSED="proposed"; SELECTED="selected"; REJECTED="rejected"; ARCHIVED="archived"
def _values(items): return [item.value for item in items]

class DesignDirection(Base):
    __tablename__ = "design_directions"
    __table_args__ = (ForeignKeyConstraint(["project_id", "intent_id"], ["project_intents.project_id", "project_intents.id"], name="fk_design_directions_intent_revision"),
                      Index("uq_direction_one_selected_per_project", "project_id", unique=True, postgresql_where=text("status = 'selected'"), sqlite_where=text("status = 'selected'")))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    intent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("project_intents.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    visual_language: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    typography_direction: Mapped[str | None] = mapped_column(Text)
    color_direction: Mapped[str | None] = mapped_column(Text)
    layout_direction: Mapped[str | None] = mapped_column(Text)
    navigation_direction: Mapped[str | None] = mapped_column(Text)
    imagery_direction: Mapped[str | None] = mapped_column(Text)
    motion_direction: Mapped[str | None] = mapped_column(Text)
    component_direction: Mapped[str | None] = mapped_column(Text)
    density: Mapped[str | None] = mapped_column(String(80))
    emotional_tone: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    target_audience_fit: Mapped[str | None] = mapped_column(Text)
    strengths: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    tradeoffs: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    risks: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    supporting_research_ids: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    provenance: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    status: Mapped[DirectionStatus] = mapped_column(SAEnum(DirectionStatus, name="direction_status", values_callable=_values), nullable=False, default=DirectionStatus.PROPOSED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
