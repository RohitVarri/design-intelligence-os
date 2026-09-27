"""Injectable runtime dependencies for API handlers and host integration."""
from app.core.actors import AuthorizationPolicy, get_actor_context, get_authorization_policy
from app.providers.router import ModelRouter
from app.providers.runtime import ProviderRuntime, RuntimePolicy
from app.core.config import get_settings
from app.services.operation_executor import OperationExecutor
from app.services.research_execution import ResearchExecutionService


def get_model_router() -> ModelRouter:
    """Return a vendor-neutral router. Production hosts register configured adapters."""
    return ModelRouter()


def get_provider_runtime() -> ProviderRuntime:
    """Runtime factory kept injectable so tests and deployments can provide adapters."""
    settings = get_settings()
    return ProviderRuntime(get_model_router(), RuntimePolicy(settings.provider_timeout_seconds, settings.provider_retry_limit, settings.provider_fallback_limit), AuthorizationPolicy())


def get_operation_executor() -> OperationExecutor:
    return OperationExecutor(AuthorizationPolicy())


def get_research_execution_service() -> ResearchExecutionService:
    return ResearchExecutionService()


__all__ = ["get_actor_context", "get_authorization_policy", "get_model_router", "get_provider_runtime", "get_operation_executor", "get_research_execution_service"]
