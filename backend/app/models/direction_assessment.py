"""Evidence-bearing assessment observations without aggregate winner scores."""
import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Float, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class AssessmentCriterion(str, Enum):
    AUDIENCE_FIT="audience_fit"; GOAL_ALIGNMENT="goal_alignment"; BRAND_ALIGNMENT="brand_alignment"
    USABILITY="usability"; DIFFERENTIATION="differentiation"; ACCESSIBILITY="accessibility"
    PERFORMANCE="performance"; SCALABILITY="scalability"; IMPLEMENTATION_COMPLEXITY="implementation_complexity"
def _values(items): return [item.value for item in items]

class DesignDirectionAssessment(Base):
    __tablename__ = "design_direction_assessments"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    direction_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("design_directions.id", ondelete="CASCADE"), nullable=False, index=True)
    criterion: Mapped[AssessmentCriterion] = mapped_column(SAEnum(AssessmentCriterion, name="assessment_criterion", values_callable=_values), nullable=False)
    observation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    tradeoff: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
