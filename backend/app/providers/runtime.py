"""Provider execution, validation, retry, fallback, and AI Run persistence."""
import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Type
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session
from app.core.actors import ActorContext, AuthorizationPolicy
from app.models.ai_candidate import AIOutputCandidate
from app.models.ai_run import AIRun, AIRunStatus
from app.providers.contracts import ProviderResult, TaskType
from app.providers.router import ModelRouter


@dataclass(frozen=True)
class RuntimePolicy:
    timeout_seconds: float = 20.0
    retries_per_provider: int = 1
    max_fallback_providers: int = 2


@dataclass(frozen=True)
class RuntimeResult:
    run: AIRun
    candidate: AIOutputCandidate | None
    accepted: bool


class ProviderRuntime:
    def __init__(self, router: ModelRouter, policy: RuntimePolicy | None = None, authorization: AuthorizationPolicy | None = None):
        self.router = router
        self.policy = policy or RuntimePolicy()
        self.authorization = authorization or AuthorizationPolicy()

    def execute_sync(self, db: Session, **kwargs: Any) -> RuntimeResult:
        """Synchronous adapter for FastAPI's synchronous service layer."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.execute(db, **kwargs))
        raise RuntimeError("execute_sync cannot run inside an active event loop")

    async def execute(self, db: Session, *, project_id: uuid.UUID, intent_id: uuid.UUID | None, task: TaskType,
                      payload: dict[str, Any], output_schema: Type[BaseModel], actor: ActorContext,
                      context_references: dict[str, Any] | None = None, required_capabilities: set[str] | None = None) -> RuntimeResult:
        self.authorization.require(actor, "propose")
        excluded: set[str] = set()
        attempts_total = 0
        fallback_used = False
        final_run: AIRun | None = None
        for provider_index in range(self.policy.max_fallback_providers + 1):
            try:
                registration, decision = self.router.route(task, required_capabilities, excluded)
            except LookupError as exc:
                if final_run is None:
                    final_run = AIRun(project_id=project_id, intent_id=intent_id, task_type=task.value, provider="none", model="none", status=AIRunStatus.FAILED, error=str(exc), context_references=context_references or {})
                    db.add(final_run); db.flush()
                return RuntimeResult(final_run, None, False)
            run = AIRun(project_id=project_id, intent_id=intent_id, task_type=task.value, provider=registration.provider.name,
                        model=registration.model, routing_decision={"task":decision.task.value,"provider":decision.provider,"model":decision.model,
                        "required_capabilities":list(decision.required_capabilities),"matched_capabilities":list(decision.matched_capabilities),
                        "policy":decision.policy,"reason":decision.reason,"priority":decision.priority},
                        context_references=context_references or {}, provenance={"actor_type":actor.actor_type.value if actor.actor_type else None,"actor_id":actor.actor_id})
            db.add(run); db.flush()
            final_run = run
            start = time.monotonic()
            for attempt in range(self.policy.retries_per_provider + 1):
                attempts_total += 1
                try:
                    response = await asyncio.wait_for(registration.provider.generate(task=task, model=registration.model, payload=payload), timeout=self.policy.timeout_seconds)
                    run.request_id = response.request_id
                    validated = output_schema.model_validate(response.payload, strict=True)
                    output = validated.model_dump(mode="json")
                    run.output_reference = response.output_reference
                    run.input_tokens = response.usage.get("input_tokens")
                    run.output_tokens = response.usage.get("output_tokens")
                    run.status = AIRunStatus.SUCCEEDED
                    candidate = AIOutputCandidate(run_id=run.id, project_id=project_id, intent_id=intent_id, candidate_type=task.value,
                        schema_version="1", payload=output, validation_status="valid", provenance={"source_type":"ai_proposal","run_id":str(run.id),"provider":run.provider,"model":run.model})
                    db.add(candidate)
                    run.retry_count = attempts_total - 1
                    run.fallback_used = fallback_used
                    run.latency_ms = int((time.monotonic() - start) * 1000)
                    run.completed_at = datetime.now(timezone.utc)
                    db.flush()
                    return RuntimeResult(run, candidate, True)
                except ValidationError as exc:
                    error = "structured output failed schema validation"
                    run.status = AIRunStatus.MALFORMED
                    run.error = error
                    run.retry_count = attempts_total - 1
                    run.fallback_used = fallback_used
                    run.latency_ms = int((time.monotonic() - start) * 1000)
                    run.completed_at = datetime.now(timezone.utc)
                    candidate = AIOutputCandidate(run_id=run.id, project_id=project_id, intent_id=intent_id, candidate_type=task.value,
                        schema_version="1", payload=_safe_json(response.payload), validation_status="quarantined", validation_error=f"{len(exc.errors())} validation error(s)",
                        provenance={"source_type":"ai_proposal","run_id":str(run.id),"quarantined":True})
                    db.add(candidate); db.flush()
                    return RuntimeResult(run, candidate, False)
                except (asyncio.TimeoutError, ConnectionError) as exc:
                    run.error = "provider timeout" if isinstance(exc, asyncio.TimeoutError) else "transient provider failure"
                    run.retry_count = attempts_total
                    if attempt >= self.policy.retries_per_provider: break
                except Exception:
                    run.error = "provider execution failed"
                    run.status = AIRunStatus.FAILED
                    break
            run.status = AIRunStatus.FAILED
            run.completed_at = datetime.now(timezone.utc)
            run.latency_ms = int((time.monotonic() - start) * 1000)
            db.flush()
            excluded.add(registration.provider.name)
            if provider_index < self.policy.max_fallback_providers:
                fallback_used = True
        return RuntimeResult(final_run, None, False)


def _safe_json(payload: Any) -> dict:
    try:
        return json.loads(json.dumps(payload, default=lambda _: "<non-serializable>"))
    except (TypeError, ValueError):
        return {"quarantined": True, "payload_type": type(payload).__name__}
