"""Question generation, answer, and status schemas."""
import uuid
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from app.models.question import QuestionCategory, QuestionPriority, QuestionStatus

class QuestionCreate(BaseModel):
    question: str = Field(min_length=5)
    category: QuestionCategory
    reason: str = Field(min_length=1)
    intent_field: str | None = None
    answer_type: Literal["text", "single_choice", "multi_choice", "boolean", "number"] = "text"
    options: list[Any] = Field(default_factory=list)
    required: bool = True

class QuestionUpdate(BaseModel):
    status: QuestionStatus | None = None
    reason: str | None = None

class QuestionAnswer(BaseModel):
    answer: Any

class QuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    intent_id: uuid.UUID
    question: str
    category: QuestionCategory
    priority: QuestionPriority
    impact: str
    impact_score: float
    reason: str
    answer_type: str
    options: list[Any]
    required: bool
    status: QuestionStatus
    answer: Any
    intent_field: str | None
    created_at: datetime
    answered_at: datetime | None
