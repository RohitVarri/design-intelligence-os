"""Research plans generated from structured intent."""
import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Uuid, func, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class ResearchPlanStatus(str, Enum):
    DRAFT="draft"; QUEUED="queued"; RUNNING="running"; COMPLETED="completed"; FAILED="failed"
def _values(items): return [item.value for item in items]

class ResearchPlan(Base):
    __tablename__ = "research_plans"
    __table_args__ = (ForeignKeyConstraint(["project_id", "intent_id"], ["project_intents.project_id", "project_intents.id"], name="fk_research_plans_intent_revision"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    intent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("project_intents.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[ResearchPlanStatus] = mapped_column(SAEnum(ResearchPlanStatus, name="research_plan_status", values_callable=_values), nullable=False, default=ResearchPlanStatus.DRAFT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
