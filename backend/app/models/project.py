"""Project model."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid, func, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Project(Base):
    """A user-owned workspace for design state and its history."""

    __tablename__ = "projects"
    __table_args__ = (ForeignKeyConstraint(["id", "current_intent_id"], ["project_intents.project_id", "project_intents.id"], name="fk_project_current_intent_revision", use_alter=True),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    current_intent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    design_state: Mapped["DesignState | None"] = relationship(back_populates="project", cascade="all, delete-orphan", uselist=False)
    versions: Mapped[list["DesignVersion"]] = relationship(back_populates="project", cascade="all, delete-orphan")
