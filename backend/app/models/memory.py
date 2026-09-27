"""Project memory model with explicit trust classification."""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, JSON, String, Text, Uuid, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MemoryTrust(str, Enum):
    """Trust status of stored project memory."""
    USER_APPROVED = "user_approved"
    AI_SUGGESTION = "ai_suggestion"
    IMPORTED_UNTRUSTED = "imported_untrusted"


class DesignMemory(Base):
    """Persistent project knowledge with provenance and approval state."""

    __tablename__ = "design_memories"
    __table_args__ = (UniqueConstraint("source_operation_id", name="uq_design_memory_source_operation"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    trust: Mapped[MemoryTrust] = mapped_column(SAEnum(MemoryTrust, name="memory_trust", values_callable=lambda values: [item.value for item in values]), nullable=False)
    provenance: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    source_operation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("design_operations.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
