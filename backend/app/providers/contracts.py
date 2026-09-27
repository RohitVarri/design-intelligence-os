"""Vendor-neutral provider and routing contracts."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class TaskType(str, Enum):
    INTENT_EXTRACTION = "intent_extraction"
    QUESTION_GENERATION = "question_generation"
    RESEARCH_QUERY = "research_query"
    RESEARCH_SYNTHESIS = "research_synthesis"
    PROPOSAL_GENERATION = "proposal_generation"
    DESIGN_PLAN_GENERATION = "design_plan_generation"


@dataclass(frozen=True)
class ProviderResult:
    payload: Any
    request_id: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    output_reference: str | None = None


@dataclass(frozen=True)
class RoutingDecision:
    task: TaskType
    provider: str
    model: str
    required_capabilities: tuple[str, ...]
    matched_capabilities: tuple[str, ...]
    policy: str
    reason: str
    priority: int


class ModelProvider(Protocol):
    """Async provider adapter. It returns raw structured data, never writes to storage."""
    name: str
    capabilities: frozenset[str]
    available: bool

    async def generate(self, *, task: TaskType, model: str, payload: dict[str, Any]) -> ProviderResult: ...
