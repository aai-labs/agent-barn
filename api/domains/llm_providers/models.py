"""LLM Provider Connections: the provider accounts Agents reach models through.

The key is stored Fernet-encrypted, with its last four characters kept apart for display.
A slug stays unique among deleted connections too, so it is never reused.
A known provider has one connection, whose slug is its provider type. An Azure or Custom
connection has a slug of its own, never a provider type, and a base URL.
A connection's models each carry an input and output price above zero, per token.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, PlainSerializer, SecretStr, field_validator, model_validator
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel

MAX_SLUG_LENGTH = 32
MAX_NAME_LENGTH = 64
MAX_API_KEY_LENGTH = 512
MAX_BASE_URL_LENGTH = 2048
SLUG_PATTERN = "^[a-z0-9]+(-[a-z0-9]+)*$"
MAX_MODEL_ID_LENGTH = 200
MODEL_ID_PATTERN = "^[A-Za-z0-9._:/-]+$"
MAX_PRICE_KEY_LENGTH = 256
PRICE_PRECISION = 24
PRICE_SCALE = 18
MAX_MODELS_PER_CONNECTION = 50

# The connection the migration seeds. Kept here for tests that reset the table to it; the
# migration carries its own copy, as migrations do.
OPENROUTER_CONNECTION_ID = UUID("00000000-0000-7000-8000-00000000a4e0")
OPENROUTER_SLUG = "openrouter"
OPENROUTER_NAME = "OpenRouter"

# The LiteLLM route carrying the stored OpenRouter key. Order 1 puts it ahead of the
# config-file route that reads OPENROUTER_API_KEY, which is order 2.
OPENROUTER_ROUTE_ID = "agentbarn:openrouter"
OPENROUTER_ROUTE_MODEL = "openrouter/*"
OPENROUTER_ROUTE_API_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_ROUTE_ORDER = 1

ExactPrice = Annotated[Decimal, PlainSerializer(lambda price: format(price, "f"), return_type=str)]


class ProviderType(StrEnum):
    OPENROUTER = "openrouter"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"
    XAI = "xai"
    DEEPSEEK = "deepseek"
    FIREWORKS = "fireworks"
    NOVITA = "novita"
    AZURE = "azure"
    CUSTOM = "custom"


class PriceSource(StrEnum):
    LITELLM = "litellm"
    MANUAL = "manual"


BASE_URL_PROVIDER_TYPES = (ProviderType.AZURE, ProviderType.CUSTOM)
KNOWN_PROVIDER_NAMES = {
    ProviderType.OPENROUTER: OPENROUTER_NAME,
    ProviderType.ANTHROPIC: "Anthropic",
    ProviderType.OPENAI: "OpenAI",
    ProviderType.GEMINI: "Gemini",
    ProviderType.XAI: "xAI",
    ProviderType.DEEPSEEK: "DeepSeek",
    ProviderType.FIREWORKS: "Fireworks",
    ProviderType.NOVITA: "Novita",
}


def _sql_values(members: tuple[StrEnum, ...]) -> str:
    return ", ".join(f"'{member.value}'" for member in members)


_ALL_TYPES_SQL = _sql_values(tuple(ProviderType))
_BASE_URL_TYPES_SQL = _sql_values(BASE_URL_PROVIDER_TYPES)
_PRICE_SOURCES_SQL = _sql_values(tuple(PriceSource))


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
        sa.CheckConstraint(
            f"provider_type IN ({_ALL_TYPES_SQL})", name="ck_llm_provider_connection_provider_type_known"
        ),
        sa.CheckConstraint(
            "(api_key_encrypted IS NULL) = (api_key_last4 IS NULL)", name="ck_llm_provider_connection_key_complete"
        ),
        sa.CheckConstraint(
            f"(base_url IS NOT NULL) = (provider_type IN ({_BASE_URL_TYPES_SQL}))",
            name="ck_llm_provider_connection_base_url_by_type",
        ),
        sa.CheckConstraint(
            f"provider_type IN ({_BASE_URL_TYPES_SQL}) OR slug = provider_type",
            name="ck_llm_provider_connection_known_slug_is_type",
        ),
        sa.CheckConstraint(
            f"provider_type NOT IN ({_BASE_URL_TYPES_SQL}) OR slug NOT IN ({_ALL_TYPES_SQL})",
            name="ck_llm_provider_connection_own_slug_not_a_type",
        ),
    )

    slug: str = SqlField(max_length=MAX_SLUG_LENGTH, sa_column_kwargs={"unique": True})
    name: str = SqlField(max_length=MAX_NAME_LENGTH)
    provider_type: ProviderType = SqlField(sa_column=Column(_string_enum(ProviderType, 32), nullable=False))
    api_key_encrypted: str | None = SqlField(default=None, repr=False)
    api_key_last4: str | None = SqlField(default=None, max_length=4)
    base_url: str | None = SqlField(default=None, max_length=MAX_BASE_URL_LENGTH)
    updated_by: UUID | None = SqlField(default=None, foreign_key="user.id", ondelete="SET NULL")
    deleted_at: datetime | None = SqlField(default=None, sa_column=Column(sa.DateTime(timezone=True), nullable=True))


def _price_column() -> Column:
    return Column(sa.Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False)


class LlmProviderModel(BaseModel, table=True):
    __tablename__: str = "llm_provider_model"
    __table_args__ = (
        sa.UniqueConstraint("connection_id", "model_id", name="uq_llm_provider_model_connection_model"),
        sa.CheckConstraint(f"model_id ~ '{MODEL_ID_PATTERN}'", name="ck_llm_provider_model_model_id_format"),
        sa.CheckConstraint("input_cost_per_token > 0", name="ck_llm_provider_model_input_price_positive"),
        sa.CheckConstraint("output_cost_per_token > 0", name="ck_llm_provider_model_output_price_positive"),
        sa.CheckConstraint(
            "cache_read_input_token_cost >= 0", name="ck_llm_provider_model_cache_read_price_not_negative"
        ),
        sa.CheckConstraint(
            "cache_creation_input_token_cost >= 0", name="ck_llm_provider_model_cache_creation_price_not_negative"
        ),
        sa.CheckConstraint(f"price_source IN ({_PRICE_SOURCES_SQL})", name="ck_llm_provider_model_price_source_known"),
        sa.CheckConstraint(
            f"(litellm_price_key IS NOT NULL) = (price_source = '{PriceSource.LITELLM.value}')",
            name="ck_llm_provider_model_price_key_by_source",
        ),
    )

    connection_id: UUID = SqlField(foreign_key="llm_provider_connection.id", nullable=False)
    model_id: str = SqlField(max_length=MAX_MODEL_ID_LENGTH)
    input_cost_per_token: Decimal = SqlField(sa_column=_price_column())
    output_cost_per_token: Decimal = SqlField(sa_column=_price_column())
    cache_read_input_token_cost: Decimal = SqlField(sa_column=_price_column())
    cache_creation_input_token_cost: Decimal = SqlField(sa_column=_price_column())
    price_source: PriceSource = SqlField(sa_column=Column(_string_enum(PriceSource, 16), nullable=False))
    litellm_price_key: str | None = SqlField(default=None, max_length=MAX_PRICE_KEY_LENGTH)


class LlmProviderConnectionRead(PydanticBaseModel):
    """What a Platform Administrator sees of a connection: never the key itself."""

    slug: str
    name: str
    provider_type: ProviderType
    base_url: str | None = None
    has_api_key: bool
    api_key_last4: str | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None
    env_key_configured: bool


class LlmProviderModelRead(PydanticBaseModel):
    """A stored model and its per-token prices, each an exact fixed-point decimal string."""

    model_id: str
    input_cost_per_token: ExactPrice
    output_cost_per_token: ExactPrice
    cache_read_input_token_cost: ExactPrice
    cache_creation_input_token_cost: ExactPrice
    price_source: PriceSource
    litellm_price_key: str | None = None


class LlmProviderCatalogueEntryRead(PydanticBaseModel):
    """A model the provider lists, with LiteLLM's chat prices for it when it has them, all four
    or none, and whether this connection stores it at other prices."""

    model_id: str
    stored: bool
    litellm_price_key: str | None = None
    input_cost_per_token: ExactPrice | None = None
    output_cost_per_token: ExactPrice | None = None
    cache_read_input_token_cost: ExactPrice | None = None
    cache_creation_input_token_cost: ExactPrice | None = None
    prices_differ: bool


@dataclass(frozen=True)
class LlmProviderModelPrices:
    """A model's four per-token prices and where they came from."""

    input_cost_per_token: Decimal
    output_cost_per_token: Decimal
    cache_read_input_token_cost: Decimal
    cache_creation_input_token_cost: Decimal
    price_source: PriceSource
    litellm_price_key: str | None = None

    @classmethod
    def of(cls, model: LlmProviderModel) -> Self:
        return cls(
            model.input_cost_per_token,
            model.output_cost_per_token,
            model.cache_read_input_token_cost,
            model.cache_creation_input_token_cost,
            model.price_source,
            model.litellm_price_key,
        )

    def amounts(self) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        return (
            self.input_cost_per_token,
            self.output_cost_per_token,
            self.cache_read_input_token_cost,
            self.cache_creation_input_token_cost,
        )


class LlmProviderTypedPrices(PydanticBaseModel):
    """Typed per-token prices as decimal strings, whose rules the service checks so that a refusal
    can say which one was broken."""

    model_config = ConfigDict(extra="forbid")

    input_cost_per_token: str | None = None
    output_cost_per_token: str | None = None
    cache_read_input_token_cost: str | None = None
    cache_creation_input_token_cost: str | None = None


class LlmProviderModelChoice(PydanticBaseModel):
    """A model to store: `"litellm"` takes LiteLLM's chat price, `"stored"` keeps its stored prices,
    and typed prices are stored as `manual`."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    price: str | LlmProviderTypedPrices


class LlmProviderModelsReplace(PydanticBaseModel):
    """Every model the connection should have; any stored model left out is removed."""

    model_config = ConfigDict(extra="forbid")

    models: list[LlmProviderModelChoice]


class LlmProviderConnectionCreate(PydanticBaseModel):
    """A known provider takes only its key. Azure and Custom take a slug, name and base URL too,
    whose rules the service checks so that a refusal can say which one was broken."""

    model_config = ConfigDict(extra="forbid")

    provider_type: ProviderType
    api_key: SecretStr
    slug: str | None = None
    name: str | None = None
    base_url: str | None = None

    @model_validator(mode="after")
    def _fields_match_the_provider_type(self) -> Self:
        own_fields = (self.slug, self.name, self.base_url)
        if self.provider_type in BASE_URL_PROVIDER_TYPES:
            if None in own_fields:
                raise ValueError("Azure and Custom connections need a slug, a name and a base URL.")
        elif any(field is not None for field in own_fields):
            raise ValueError("A known provider takes no slug, name or base URL.")
        return self

    @field_validator("api_key")
    @classmethod
    def _trimmed_and_bounded(cls, value: SecretStr) -> SecretStr:
        trimmed = value.get_secret_value().strip()
        if not trimmed or len(trimmed) > MAX_API_KEY_LENGTH:
            raise ValueError("Enter a key.")
        return SecretStr(trimmed)


class LlmProviderKeyReplace(PydanticBaseModel):
    """A new key and, for Azure or Custom only, a new base URL, whose rules the service checks."""

    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr
    base_url: str | None = None

    @field_validator("api_key")
    @classmethod
    def _trimmed_and_bounded(cls, value: SecretStr) -> SecretStr:
        trimmed = value.get_secret_value().strip()
        if not trimmed or len(trimmed) > MAX_API_KEY_LENGTH:
            raise ValueError("Enter a key.")
        return SecretStr(trimmed)
