"""Design decision model."""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, JSON, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DecisionSource(str, Enum):
    """Origin of a recorded design decision."""
    USER = "user"
    AI = "ai"
    RESEARCH = "research"
    IMPORTED_REFERENCE = "imported_reference"
    SYSTEM = "system"


class DesignDecision(Base):
    """Decision and rationale associated with a project."""

    __tablename__ = "design_decisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[DecisionSource] = mapped_column(SAEnum(DecisionSource, name="decision_source", values_callable=lambda values: [item.value for item in values]), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    provenance: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
