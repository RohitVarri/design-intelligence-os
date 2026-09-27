"""Trace record for each provider execution."""
import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Float, Integer, JSON, String, Text, Uuid, func, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class AIRunStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    MALFORMED = "malformed"
    QUARANTINED = "quarantined"


def _values(items): return [item.value for item in items]


class AIRun(Base):
    __tablename__ = "ai_runs"
    __table_args__ = (CheckConstraint("retry_count >= 0", name="ck_ai_run_retry_nonnegative"),
                      CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ck_ai_run_input_tokens_nonnegative"),
                      CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ck_ai_run_output_tokens_nonnegative"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    intent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("project_intents.id", ondelete="SET NULL"), index=True)
    task_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(300))
    routing_decision: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    context_references: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    input_reference: Mapped[str | None] = mapped_column(Text)
    output_reference: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fallback_used: Mapped[bool] = mapped_column(nullable=False, default=False)
    status: Mapped[AIRunStatus] = mapped_column(SAEnum(AIRunStatus, name="ai_run_status", values_callable=_values), nullable=False, default=AIRunStatus.RUNNING)
    error: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
