"""Current structured design state model."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DesignState(Base):
    """Mutable current snapshot; each meaningful update also creates an immutable version."""

    __tablename__ = "design_states"

    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    state: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("design_versions.id", use_alter=True, name="fk_design_state_current_version", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    project: Mapped["Project"] = relationship(back_populates="design_state", foreign_keys=[project_id])
