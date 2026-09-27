"""Deterministic fake provider behaviors for offline tests."""
import asyncio
import json
from collections import defaultdict, deque
from typing import Any
from app.providers.contracts import ProviderResult, TaskType
from app.providers.schemas import IntentCandidateOutput, QuestionCandidatesOutput
from app.schemas.design_plan import DesignPlanOutput


class FakeModelProvider:
    name = "fake"
    available = True
    capabilities = frozenset({"structured_output", "text", "research"})

    def __init__(self, responses: dict[TaskType, list[Any]] | None = None, behaviors: list[str] | None = None):
        self.responses = {task: deque(values) for task, values in (responses or {}).items()}
        self.behaviors = deque(behaviors or [])
        self.calls: list[TaskType] = []

    async def generate(self, *, task: TaskType, model: str, payload: dict[str, Any]) -> ProviderResult:
        self.calls.append(task)
        behavior = self.behaviors.popleft() if self.behaviors else "success"
        if behavior == "timeout":
            await asyncio.sleep(10)
        if behavior == "transient_failure":
            raise ConnectionError("temporary provider failure")
        if behavior == "permanent_failure":
            raise RuntimeError("provider rejected request")
        if behavior == "malformed":
            return ProviderResult({"unexpected": object()}, request_id="fake-malformed")
        queue = self.responses.get(task)
        if queue:
            return queue.popleft()
        if task == TaskType.INTENT_EXTRACTION:
            return ProviderResult(IntentCandidateOutput(fields={}, summary="No additional reliable fields found.").model_dump(), request_id="fake-intent")
        if task == TaskType.QUESTION_GENERATION:
            return ProviderResult(QuestionCandidatesOutput(questions=[]).model_dump(), request_id="fake-questions")
        if task == TaskType.DESIGN_PLAN_GENERATION:
            from app.services.design_plans import DeterministicDesignPlanEngine
            output = DeterministicDesignPlanEngine().generate(payload["reasoning_context"])
            validated = DesignPlanOutput.model_validate_json(json.dumps(output), strict=True)
            return ProviderResult(validated.model_dump(), request_id="fake-design-plan")
        return ProviderResult({"items": [], "summary": "No candidates."}, request_id=f"fake-{task.value}")
