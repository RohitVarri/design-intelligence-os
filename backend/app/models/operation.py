"""Proposed design operations form the approval boundary before future state edits."""
import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, JSON, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class OperationType(str, Enum): CREATE="create"; UPDATE="update"; DELETE="delete"; MOVE="move"; REORDER="reorder"; REPLACE="replace"; SELECT_DIRECTION="select_direction"; UPDATE_REQUIREMENT="update_requirement"; UPDATE_INTENT="update_intent"
class OperationActor(str, Enum): USER="user"; AI="ai"; SYSTEM="system"
class OperationSource(str, Enum): USER_REQUEST="user_request"; USER_ANSWER="user_answer"; AI_PROPOSAL="ai_proposal"; RESEARCH="research"; IMPORTED_REFERENCE="imported_reference"; SYSTEM="system"
class OperationStatus(str, Enum): PROPOSED="proposed"; VALIDATED="validated"; PREVIEWED="previewed"; APPROVED="approved"; APPLIED="applied"; REJECTED="rejected"
def _values(items): return [item.value for item in items]

class DesignOperation(Base):
    __tablename__ = "design_operations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    operation_type: Mapped[OperationType] = mapped_column(SAEnum(OperationType, name="operation_type", values_callable=_values), nullable=False)
    actor: Mapped[OperationActor] = mapped_column(SAEnum(OperationActor, name="operation_actor", values_callable=_values), nullable=False)
    target: Mapped[str] = mapped_column(String(500), nullable=False)
    property: Mapped[str | None] = mapped_column(String(500))
    old_value: Mapped[dict | list | str | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    new_value: Mapped[dict | list | str | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    scope: Mapped[str] = mapped_column(String(100), nullable=False, default="project")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[OperationSource] = mapped_column(SAEnum(OperationSource, name="operation_source", values_callable=_values), nullable=False)
    status: Mapped[OperationStatus] = mapped_column(SAEnum(OperationStatus, name="operation_status", values_callable=_values), nullable=False, default=OperationStatus.PROPOSED)
    parent_operation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("design_operations.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
