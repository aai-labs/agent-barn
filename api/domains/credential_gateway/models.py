"""Gateway Token persistence and DTOs.

A Gateway Token is a credential to Agent Barn, not to a provider. It identifies one
``(Agent, provider)`` pair to the credential gateway, which then applies the real
provider credential on the agent's behalf. See
``docs/adr/2026-09-02-credential-gateway-egress-modes.md``.
"""

import datetime
import hashlib
import secrets
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.domains.agents.models import SecretProvider
from api.infrastructure.postgres.models import BaseModel

#: Distinguishes a gateway token at a glance in logs and pod env, and gives secret
#: scanners something to match on.
TOKEN_PREFIX = "agt_"

#: 32 bytes of CSPRNG entropy, the same strength as the Ingest and Communications
#: runtime credentials.
_TOKEN_ENTROPY_BYTES = 32


def issue_token_value() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_ENTROPY_BYTES)


def gateway_token_env_var(provider: SecretProvider) -> str:
    """``SecretProvider.GITHUB`` -> ``"AF_GATEWAY_TOKEN_GITHUB"``.

    One variable per provider rather than one shared token, so revoking a single
    Integration does not invalidate the Agent's access to the others.
    """
    return f"AF_GATEWAY_TOKEN_{provider.value.upper()}"


def hash_token(value: str) -> str:
    """Hash a token for storage and lookup.

    Deliberately a plain SHA-256 rather than the reversible encryption used for the
    Ingest and Communications keys, for two reasons. The gateway receives only a bearer
    token — there is no Agent id in the path to narrow by — so it must *find* the row by
    what it was given, and Fernet ciphertext is non-deterministic and therefore not
    indexable. And nothing ever needs the plaintext back, so storing a recoverable form
    would be strictly more dangerous.

    A slow password hash would be wrong here: the input is 32 bytes of CSPRNG entropy
    rather than a human-chosen secret, so it is not brute-forceable, and this runs on
    every agent tool call.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class GatewayToken(BaseModel, table=True):
    __tablename__: str = "gateway_token"

    __table_args__ = (
        # Composite FK against agent's (id, organization_id) unique constraint: the
        # denormalized organization_id is on the hot resolution path, and this is what
        # stops it drifting from the Agent's own tenant.
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_gateway_token_agent_organization",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name="uq_gateway_token_hash"),
        # At most one live token per (Agent, provider). Rotation revokes the old row and
        # inserts a new one, so revoked rows accumulate for audit without blocking.
        sa.Index(
            "uq_gateway_token_active",
            "agent_id",
            "provider",
            unique=True,
            postgresql_where=sa.text("revoked_at IS NULL"),
        ),
        sa.Index("ix_gateway_token_organization", "organization_id"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    agent_id: UUID = SqlField(nullable=False)
    provider: SecretProvider = SqlField(sa_column=Column(sa.String(50), nullable=False))
    token_hash: str = SqlField(nullable=False, max_length=64)
    revoked_at: datetime.datetime | None = SqlField(
        default=None,
        sa_column=Column(sa.DateTime(timezone=True), nullable=True),
    )
    #: Best-effort observability, updated on resolution. Never used for authorization.
    last_used_at: datetime.datetime | None = SqlField(
        default=None,
        sa_column=Column(sa.DateTime(timezone=True), nullable=True),
    )


class IssuedGatewayToken(PydanticBaseModel):
    """One freshly issued token. The plaintext exists only here and in the pod Secret."""

    provider: SecretProvider
    value: str


class GatewayTokenResolution(PydanticBaseModel):
    """Who a presented token belongs to. Carries no credential material."""

    agent_id: UUID
    organization_id: UUID
    provider: SecretProvider


class BrokeredTokenRead(PydanticBaseModel):
    """A short-lived upstream credential handed to the agent pod.

    Carries a relative lifetime rather than an absolute expiry so the pod does not have
    to agree with the gateway about the clock.
    """

    access_token: str
    expires_in: int
    scopes: list[str] = []
