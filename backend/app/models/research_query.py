"""Individual planned research questions and their execution status."""
import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class ResearchQueryStatus(str, Enum):
    QUEUED="queued"; RUNNING="running"; COMPLETED="completed"; FAILED="failed"; SKIPPED="skipped"
class ResearchQueryPriority(str, Enum):
    CRITICAL="critical"; HIGH="high"; MEDIUM="medium"; LOW="low"
def _values(items): return [item.value for item in items]

class ResearchQuery(Base):
    __tablename__ = "research_queries"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("research_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    research_area: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[ResearchQueryPriority] = mapped_column(SAEnum(ResearchQueryPriority, name="research_query_priority", values_callable=_values), nullable=False)
    status: Mapped[ResearchQueryStatus] = mapped_column(SAEnum(ResearchQueryStatus, name="research_query_status", values_callable=_values), nullable=False, default=ResearchQueryStatus.QUEUED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
