"""High-impact clarification questions associated with an intent."""
import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Float, JSON, String, Text, Uuid, func, ForeignKeyConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class QuestionCategory(str, Enum):
    GOAL="goal"; AUDIENCE="audience"; CONTENT="content"; FUNCTIONALITY="functionality"
    PLATFORM="platform"; BRANDING="branding"; VISUAL="visual"; UX="UX"
    ACCESSIBILITY="accessibility"; TECHNICAL="technical"; BUSINESS="business"
    CONSTRAINTS="constraints"; REFERENCES="references"
class QuestionPriority(str, Enum):
    CRITICAL="critical"; HIGH="high"; MEDIUM="medium"; LOW="low"
class QuestionStatus(str, Enum):
    OPEN="open"; ANSWERED="answered"; SKIPPED="skipped"; SUPERSEDED="superseded"
def _values(items): return [item.value for item in items]

class Question(Base):
    """A focused question with deterministic impact ranking and answer state."""
    __tablename__ = "questions"
    __table_args__ = (ForeignKeyConstraint(["project_id", "intent_id"], ["project_intents.project_id", "project_intents.id"], name="fk_questions_intent_revision"),
                      CheckConstraint("impact_score >= 0 AND impact_score <= 100", name="ck_question_impact_range"),
                      CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_question_confidence_range"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    intent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("project_intents.id", ondelete="CASCADE"), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[QuestionCategory] = mapped_column(SAEnum(QuestionCategory, name="question_category", values_callable=_values), nullable=False)
    priority: Mapped[QuestionPriority] = mapped_column(SAEnum(QuestionPriority, name="question_priority", values_callable=_values), nullable=False)
    impact: Mapped[str] = mapped_column(Text, nullable=False)
    impact_score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    answer_type: Mapped[str] = mapped_column(String(40), nullable=False, default="text")
    options: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[QuestionStatus] = mapped_column(SAEnum(QuestionStatus, name="question_status", values_callable=_values), nullable=False, default=QuestionStatus.OPEN)
    answer: Mapped[dict | list | str | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    intent_field: Mapped[str | None] = mapped_column(String(100))
    dependencies: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    suppression_reason: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
