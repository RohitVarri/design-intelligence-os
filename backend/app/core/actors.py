"""Injectable actor identity and fail-closed mutation authorization."""
from dataclasses import dataclass
from enum import Enum
from fastapi import Depends, HTTPException


class ActorType(str, Enum):
    SYSTEM = "system"
    USER = "user"
    AI = "ai"
    FAKE_TEST_ACTOR = "fake_test_actor"


@dataclass(frozen=True)
class ActorContext:
    """Trusted identity supplied by the hosting application, never by request headers."""
    actor_type: ActorType | None
    actor_id: str | None = None
    trusted: bool = False
    test_only: bool = False


def get_actor_context() -> ActorContext:
    """Return an unauthenticated context until a trusted host adapter is installed."""
    return ActorContext(actor_type=None, trusted=False)


class AuthorizationPolicy:
    """Central policy for mutable actions; AI can propose and preview only."""
    def require(self, actor: ActorContext, action: str) -> None:
        if actor.actor_type == ActorType.FAKE_TEST_ACTOR:
            if actor.test_only:
                return
            raise HTTPException(403, "Fake test actors are not valid in production")
        if not actor.trusted or actor.actor_type is None:
            if action == "preview":
                return
            raise HTTPException(403, "A trusted actor context is required")
        if action in {"approve", "apply"}:
            if actor.actor_type != ActorType.USER:
                raise HTTPException(403, "Only an authorized user may approve or apply an operation")
            return
        if action in {"propose", "preview"}:
            if actor.actor_type not in {ActorType.USER, ActorType.AI, ActorType.SYSTEM}:
                raise HTTPException(403, "Actor cannot perform this operation")
            return
        if action == "system" and actor.actor_type != ActorType.SYSTEM:
            raise HTTPException(403, "A system actor is required")
        if actor.actor_type == ActorType.AI and action not in {"propose", "preview"}:
            raise HTTPException(403, "AI actors cannot mutate approved design data")


def get_authorization_policy() -> AuthorizationPolicy:
    """Dependency hook for policy injection in tests and host applications."""
    return AuthorizationPolicy()


def require_mutation_actor(
    actor: ActorContext = Depends(get_actor_context),
    policy: AuthorizationPolicy = Depends(get_authorization_policy),
) -> ActorContext:
    """Authorize a user/system metadata mutation; AI has proposal-only rights."""
    policy.require(actor, "mutate")
    return actor
