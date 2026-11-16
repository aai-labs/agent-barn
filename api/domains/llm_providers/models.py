"""LLM Provider Connections: the provider accounts Agents reach models through.

The key is stored Fernet-encrypted, with its last four characters kept apart for display.
`key_source` records whether the key was seeded from the environment or saved by a Platform
Administrator. A slug stays unique among deleted connections too, so it is never reused.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel

MAX_SLUG_LENGTH = 32
MAX_NAME_LENGTH = 64
SLUG_PATTERN = "^[a-z0-9]+(-[a-z0-9]+)*$"

# The connection the migration seeds. Kept here for tests that reset the table to it; the
# migration carries its own copy, as migrations do.
OPENROUTER_CONNECTION_ID = UUID("00000000-0000-7000-8000-00000000a4e0")
OPENROUTER_SLUG = "openrouter"
OPENROUTER_NAME = "OpenRouter"


class ProviderType(StrEnum):
    OPENROUTER = "openrouter"


class KeySource(StrEnum):
    ENVIRONMENT = "environment"
    ADMIN = "admin"


def _string_enum(enum: type[StrEnum], length: int) -> sa.Enum:
    return sa.Enum(
        enum,
        native_enum=False,
        create_constraint=False,
        length=length,
        values_callable=lambda members: [member.value for member in members],
    )


class LlmProviderConnection(BaseModel, table=True):
    __tablename__: str = "llm_provider_connection"
    __table_args__ = (
        sa.CheckConstraint(f"slug ~ '{SLUG_PATTERN}'", name="ck_llm_provider_connection_slug_format"),
        sa.CheckConstraint("provider_type IN ('openrouter')", name="ck_llm_provider_connection_provider_type_known"),
        sa.CheckConstraint(
            "key_source IN ('environment', 'admin')", name="ck_llm_provider_connection_key_source_known"
        ),
        sa.CheckConstraint(
            "(api_key_encrypted IS NULL) = (api_key_last4 IS NULL)"
            " AND (api_key_encrypted IS NULL) = (key_source IS NULL)",
            name="ck_llm_provider_connection_key_complete",
        ),
    )

    slug: str = SqlField(max_length=MAX_SLUG_LENGTH, sa_column_kwargs={"unique": True})
    name: str = SqlField(max_length=MAX_NAME_LENGTH)
    provider_type: ProviderType = SqlField(sa_column=Column(_string_enum(ProviderType, 32), nullable=False))
    api_key_encrypted: str | None = SqlField(default=None, repr=False)
    api_key_last4: str | None = SqlField(default=None, max_length=4)
    key_source: KeySource | None = SqlField(default=None, sa_column=Column(_string_enum(KeySource, 16), nullable=True))
    updated_by: UUID | None = SqlField(default=None, foreign_key="user.id", ondelete="SET NULL")
    deleted_at: datetime | None = SqlField(default=None, sa_column=Column(sa.DateTime(timezone=True), nullable=True))


class OpenRouterConnectionRead(PydanticBaseModel):
    """What a Platform Administrator sees of the OpenRouter key: never the key itself."""

    has_api_key: bool
    api_key_last4: str | None = None
    key_source: KeySource | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None
    env_key_configured: bool
