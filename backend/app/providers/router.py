"""Capability-filtered task router with explicit, explainable policy."""
from dataclasses import dataclass
from app.providers.contracts import ModelProvider, RoutingDecision, TaskType


@dataclass(frozen=True)
class ProviderRegistration:
    provider: ModelProvider
    model: str
    tasks: frozenset[TaskType]
    capabilities: frozenset[str] = frozenset()
    priority: int = 100
    policy_name: str = "default-task-policy"


class ModelRouter:
    def __init__(self, registrations: list[ProviderRegistration] | None = None):
        self._registrations = list(registrations or [])

    def register(self, item: ProviderRegistration) -> None:
        self._registrations.append(item)

    def candidates(self, task: TaskType, required: set[str] | None = None, excluded: set[str] | None = None) -> list[ProviderRegistration]:
        required, excluded = required or set(), excluded or set()
        rows = [item for item in self._registrations if task in item.tasks and item.provider.available
                and item.provider.name not in excluded and required <= (set(item.provider.capabilities) | set(item.capabilities))]
        return sorted(rows, key=lambda item: (item.priority, item.provider.name, item.model))

    def route(self, task: TaskType, required: set[str] | None = None, excluded: set[str] | None = None) -> tuple[ProviderRegistration, RoutingDecision]:
        rows = self.candidates(task, required, excluded)
        if not rows:
            raise LookupError(f"No available provider supports task '{task.value}' and requested capabilities")
        item = rows[0]
        required = required or set()
        matched = sorted(required & (set(item.provider.capabilities) | set(item.capabilities)))
        decision = RoutingDecision(task, item.provider.name, item.model, tuple(sorted(required)), tuple(matched), item.policy_name,
            f"Selected highest-priority available provider matching task and capabilities (priority={item.priority}).", item.priority)
        return item, decision
