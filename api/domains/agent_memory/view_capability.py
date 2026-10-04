"""Short-lived capability the product API presents to the gateway's memory viewer.

It names exactly one Organization and Agent and one read-only operation. The audience
differs from user access tokens (which also use the platform signing key) and from Agent
memory credentials, so neither can stand in for it. The bank, tags, and other upstream
parameters are never part of it; the gateway derives them.
"""

import time
from dataclasses import dataclass
from uuid import UUID

import jwt
from jwt import InvalidTokenError

from api.core.config import Config
from api.domains.auth.service import JWT_ENCODING_ALGORITHM

AUDIENCE = "agentbarn-memory-viewer"
OPERATION = "list"
TTL_SECONDS = 30
_MAX_LIFETIME_SECONDS = 60


@dataclass(frozen=True)
class MemoryViewTarget:
    organization_id: UUID
    agent_id: UUID


def issue_view_capability(config: Config, organization_id: UUID, agent_id: UUID) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "aud": AUDIENCE,
            "op": OPERATION,
            "organization_id": str(organization_id),
            "agent_id": str(agent_id),
            "iat": now,
            "exp": now + TTL_SECONDS,
        },
        config.secret_signing_key,
        algorithm=JWT_ENCODING_ALGORITHM,
    )


def verify_view_capability(config: Config, token: str) -> MemoryViewTarget | None:
    """The target this server signed for viewing, or None if forged, expired, or for another purpose."""
    try:
        payload = jwt.decode(
            token,
            config.secret_signing_key,
            algorithms=[JWT_ENCODING_ALGORITHM],
            audience=AUDIENCE,
            options={"require": ["aud", "exp", "iat"]},
        )
        if payload.get("op") != OPERATION or payload["exp"] - payload["iat"] > _MAX_LIFETIME_SECONDS:
            return None
        return MemoryViewTarget(UUID(payload["organization_id"]), UUID(payload["agent_id"]))
    except InvalidTokenError, KeyError, ValueError, TypeError:
        return None
