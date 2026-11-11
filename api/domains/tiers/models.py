"""Tiers: the platform's catalog of what an Organization may use and what it pays for it.

Platform Administrators keep the catalog. A Tier sets its price, the usage it grants, its
Agent Limit, which Platforms its Agents may be reached on and which features it allows.
See `docs/features/tiers.md`.

Two Tiers are part of the system and cannot be deleted: Free, the one every new
self-signed-up Organization starts on, and `none`, for an Organization that has no Tier it
may use. Every other Tier is either paid, through a monthly subscription, or contact-only,
which only a Platform Administrator assigns.
"""

import enum
import re
from datetime import datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, HttpUrl, TypeAdapter, field_validator, model_validator
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.domains.communications.models import CommunicationPlatform
from api.domains.usage.models import TierActivation
from api.infrastructure.postgres.models import BaseModel

MAX_NAME_LENGTH = 64
MAX_TAGLINE_LENGTH = 200
MAX_PRICE_NOTE_LENGTH = 64
MAX_CONTACT_URL_LENGTH = 500
# Bounds no real Tier reaches; they only stop a typo from charging or granting a fortune.
MAX_AMOUNT_USD = Decimal(100000)
MAX_AGENT_LIMIT = 1_000
MAX_SORT_ORDER = 10_000
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


# The activations a Platform Administrator may give a Tier they add. Free and none are the
# system's own, seeded once.
CREATABLE_ACTIVATIONS = frozenset({TierActivation.PAID, TierActivation.CONTACT})


class TierFeature(str, enum.Enum):
    """A feature a Tier may allow. Platforms are allowed separately."""

    CUSTOM_AGENTS = "custom_agents"
    INTEGRATIONS = "integrations"
    TEMPLATES_AND_SKILLS = "templates_and_skills"
    WORKFLOWS = "workflows"
    AGENT_WEBHOOKS = "agent_webhooks"
    AGENT_MEMORY = "agent_memory"
    TEAM = "team"
    PRIORITY_SUPPORT = "priority_support"


FREE_TIER_KEY = "free"
NONE_TIER_KEY = "none"
SYSTEM_TIER_KEYS = frozenset({FREE_TIER_KEY, NONE_TIER_KEY})

# The settings a change Event can name, in the order a change is recorded.
TIER_SETTINGS = (
    "name",
    "tagline",
    "enabled",
    "sort_order",
    "price_usd",
    "price_note",
    "monthly_usage_usd",
    "one_time_credit_usd",
    "agent_limit",
    "allowed_platform_keys",
    "features",
    "contact_url",
)


def _money() -> Column:
    return Column(sa.Numeric(10, 2), nullable=False, server_default="0")


class Tier(BaseModel, table=True):
    """One Tier in the catalog."""

    __tablename__: str = "tier"
    __table_args__ = (
        sa.CheckConstraint("activation IN ('free', 'paid', 'contact', 'none')", name="ck_tier_activation_known"),
        sa.CheckConstraint("price_usd >= 0", name="ck_tier_price_non_negative"),
        sa.CheckConstraint("monthly_usage_usd >= 0", name="ck_tier_monthly_usage_non_negative"),
        sa.CheckConstraint("one_time_credit_usd >= 0", name="ck_tier_one_time_credit_non_negative"),
        sa.CheckConstraint("agent_limit >= 0", name="ck_tier_agent_limit_non_negative"),
        sa.CheckConstraint("activation <> 'paid' OR price_usd > 0", name="ck_tier_paid_has_price"),
        sa.CheckConstraint("activation IN ('paid', 'contact') OR price_usd = 0", name="ck_tier_unpaid_costs_nothing"),
        sa.CheckConstraint("activation = 'paid' OR monthly_usage_usd = 0", name="ck_tier_monthly_usage_only_paid"),
        sa.CheckConstraint("activation <> 'contact' OR contact_url IS NOT NULL", name="ck_tier_contact_has_url"),
        sa.CheckConstraint("activation = 'none' OR agent_limit >= 1", name="ck_tier_runs_an_agent"),
        sa.CheckConstraint(
            "activation <> 'none' OR (NOT enabled AND agent_limit = 0 AND one_time_credit_usd = 0)",
            name="ck_tier_none_grants_nothing",
        ),
        # One Free Tier and one none Tier: the system's own.
        sa.Index(
            "uq_tier_system_activation",
            "activation",
            unique=True,
            postgresql_where=sa.text("activation IN ('free', 'none')"),
        ),
    )

    key: str = SqlField(max_length=32, sa_column_kwargs={"unique": True})
    name: str = SqlField(max_length=MAX_NAME_LENGTH, sa_column_kwargs={"unique": True})
    tagline: str | None = SqlField(default=None, max_length=MAX_TAGLINE_LENGTH)
    activation: TierActivation = SqlField(
        sa_column=Column(
            sa.Enum(
                TierActivation,
                native_enum=False,
                create_constraint=False,
                length=16,
                values_callable=lambda members: [member.value for member in members],
            ),
            nullable=False,
        )
    )
    # Offered to new Organizations. Turning it off moves nobody already on it.
    enabled: bool = SqlField(default=False)
    sort_order: int = SqlField(default=0)
    # A paid Tier's monthly price; informational for a contact-only one.
    price_usd: Decimal = SqlField(default=Decimal(0), sa_column=_money())
    # How the price reads beside the amount, such as "per month".
    price_note: str | None = SqlField(default=None, max_length=MAX_PRICE_NOTE_LENGTH)
    # Credit granted on every paid invoice; what is left of it expires when the period ends.
    monthly_usage_usd: Decimal = SqlField(default=Decimal(0), sa_column=_money())
    # Credit granted once, when an Organization first comes onto the Tier.
    one_time_credit_usd: Decimal = SqlField(default=Decimal(0), sa_column=_money())
    agent_limit: int
    # Platform keys an Agent may be reached on. None: every Platform.
    allowed_platform_keys: list[str] | None = SqlField(default=None, sa_column=Column(JSONB, nullable=True))
    features: list[str] = SqlField(default_factory=list, sa_column=Column(JSONB, nullable=False, server_default="[]"))
    contact_url: str | None = SqlField(default=None, max_length=MAX_CONTACT_URL_LENGTH)

    @property
    def is_system(self) -> bool:
        return self.key in SYSTEM_TIER_KEYS


class TierRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    tagline: str | None
    activation: TierActivation
    enabled: bool
    sort_order: int
    price_usd: Decimal
    price_note: str | None
    monthly_usage_usd: Decimal
    one_time_credit_usd: Decimal
    agent_limit: int
    allowed_platform_keys: list[str] | None
    features: list[str]
    contact_url: str | None
    # Free and none: never deleted, and none never changes.
    is_system: bool
    created_at: datetime
    updated_at: datetime


class PublicTierRead(PydanticBaseModel):
    """An offered Tier as anyone may see it."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    tagline: str | None
    activation: TierActivation
    price_usd: Decimal
    price_note: str | None
    monthly_usage_usd: Decimal
    one_time_credit_usd: Decimal
    agent_limit: int
    allowed_platform_keys: list[str] | None
    features: list[str]
    contact_url: str | None


class TierHeldAgentRead(PydanticBaseModel):
    """One of the Organization's live Agents, with its Tier Hold if it is on one."""

    id: UUID
    name: str
    status: str
    suspended_at: datetime | None


class TierHeldItemRead(PydanticBaseModel):
    """A Connection, Agent Webhook or Agent Memory on a Tier Hold."""

    id: UUID
    agent_id: UUID
    agent_name: str
    name: str
    platform_key: str | None = None
    # The revision enabling a Connection or Agent Webhook again must name.
    revision: int | None = None
    suspended_at: datetime | None


class TierHoldsRead(PydanticBaseModel):
    """Everything the Organization's Tier has put on hold, for choosing what to keep."""

    agents: list[TierHeldAgentRead]
    connections: list[TierHeldItemRead]
    webhooks: list[TierHeldItemRead]
    memory: list[TierHeldItemRead]


class TierHoldPreviewRead(PydanticBaseModel):
    """What moving to `tier` would put on hold now, before the Owner decides."""

    tier: str
    agents: list[TierHeldAgentRead]
    connections: list[TierHeldItemRead]
    webhooks: list[TierHeldItemRead]
    memory: list[TierHeldItemRead]


def agent_limit_in_force(own: int | None, tier: Tier) -> int:
    """An Organization on a Tier runs up to its own Agent Limit when one is set, otherwise the
    Tier's. Holds and `over_tier` both count against this."""
    return own if own is not None else tier.agent_limit


def allows_feature(tier: Tier | None, feature: TierFeature) -> bool:
    return tier is None or feature.value in tier.features


def allows_platform(tier: Tier | None, platform_key: str) -> bool:
    return tier is None or tier.allowed_platform_keys is None or platform_key in tier.allowed_platform_keys


class OrganizationTierAssignment(PydanticBaseModel):
    """The Tier a Platform Administrator puts an Organization on; null takes it off any Tier."""

    model_config = ConfigDict(extra="forbid")

    tier_id: UUID | None


def _name(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("name must not be blank")
    return stripped


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _ordered(values: list[str] | None, members: type[enum.Enum], what: str) -> list[str] | None:
    """Known values only, stored in declaration order and once each, so equal sets compare equal."""
    if values is None:
        return None
    known = [member.value for member in members]
    unknown = sorted(set(values) - set(known))
    if unknown:
        raise ValueError(f"unknown {what}: {', '.join(unknown)}")
    return [value for value in known if value in values]


_URL = TypeAdapter(HttpUrl)


# Settings an update may send as null, because removing them means something.
_REMOVABLE_SETTINGS = frozenset({"tagline", "price_note", "allowed_platform_keys", "contact_url"})


class _TierFields(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("name", check_fields=False)
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        return None if value is None else _name(value)

    @field_validator("tagline", "price_note", check_fields=False)
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("allowed_platform_keys", check_fields=False)
    @classmethod
    def _platforms(cls, value: list[str] | None) -> list[str] | None:
        return _ordered(value, CommunicationPlatform, "platforms")

    @field_validator("features", check_fields=False)
    @classmethod
    def _features(cls, value: list[str] | None) -> list[str] | None:
        return _ordered(value, TierFeature, "features")

    @field_validator("contact_url", check_fields=False)
    @classmethod
    def _contact_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _URL.validate_python(value.strip()).scheme != "https":
            raise ValueError("the contact link must use https")
        return value.strip()


class TierCreate(_TierFields):
    key: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    tagline: str | None = Field(default=None, max_length=MAX_TAGLINE_LENGTH)
    activation: TierActivation
    enabled: bool = False
    sort_order: int = Field(default=0, ge=0, le=MAX_SORT_ORDER)
    price_usd: Decimal = Field(ge=0, le=MAX_AMOUNT_USD, max_digits=8, decimal_places=2)
    price_note: str | None = Field(default=None, max_length=MAX_PRICE_NOTE_LENGTH)
    monthly_usage_usd: Decimal = Field(default=Decimal(0), ge=0, le=MAX_AMOUNT_USD, max_digits=8, decimal_places=2)
    one_time_credit_usd: Decimal = Field(default=Decimal(0), ge=0, le=MAX_AMOUNT_USD, max_digits=8, decimal_places=2)
    agent_limit: int = Field(ge=1, le=MAX_AGENT_LIMIT)
    allowed_platform_keys: list[str] | None = Field(default=None, max_length=50)
    features: list[str] = Field(default_factory=list, max_length=50)
    contact_url: str | None = Field(default=None, max_length=MAX_CONTACT_URL_LENGTH)

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not _KEY_PATTERN.match(value):
            raise ValueError("key must be lowercase letters, digits and underscores, starting with a letter")
        return value

    @field_validator("activation")
    @classmethod
    def _creatable(cls, value: TierActivation) -> TierActivation:
        if value not in CREATABLE_ACTIVATIONS:
            raise ValueError("a new Tier is either paid or contact-only")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        check_tier_values(
            self.activation,
            price_usd=self.price_usd,
            monthly_usage_usd=self.monthly_usage_usd,
            one_time_credit_usd=self.one_time_credit_usd,
            agent_limit=self.agent_limit,
            enabled=self.enabled,
            contact_url=self.contact_url,
        )
        return self


class TierUpdate(_TierFields):
    """A partial edit. Omitting a field leaves it alone. The key and activation never change:
    the key is what links, analytics and Stripe know the Tier by."""

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    tagline: str | None = Field(default=None, max_length=MAX_TAGLINE_LENGTH)
    enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=MAX_SORT_ORDER)
    price_usd: Decimal | None = Field(default=None, ge=0, le=MAX_AMOUNT_USD, max_digits=8, decimal_places=2)
    price_note: str | None = Field(default=None, max_length=MAX_PRICE_NOTE_LENGTH)
    monthly_usage_usd: Decimal | None = Field(default=None, ge=0, le=MAX_AMOUNT_USD, max_digits=8, decimal_places=2)
    one_time_credit_usd: Decimal | None = Field(default=None, ge=0, le=MAX_AMOUNT_USD, max_digits=8, decimal_places=2)
    agent_limit: int | None = Field(default=None, ge=1, le=MAX_AGENT_LIMIT)
    allowed_platform_keys: list[str] | None = Field(default=None, max_length=50)
    features: list[str] | None = Field(default=None, max_length=50)
    contact_url: str | None = Field(default=None, max_length=MAX_CONTACT_URL_LENGTH)

    @model_validator(mode="after")
    def _required_keep_a_value(self) -> Self:
        for setting in self.model_fields_set - _REMOVABLE_SETTINGS:
            if getattr(self, setting) is None:
                raise ValueError(f"{setting} can't be removed")
        return self

    def changes(self) -> dict[str, object]:
        return self.model_dump(include=self.model_fields_set)


def check_tier_values(
    activation: TierActivation,
    *,
    price_usd: Decimal,
    monthly_usage_usd: Decimal,
    one_time_credit_usd: Decimal,
    agent_limit: int,
    enabled: bool,
    contact_url: object,
) -> None:
    """What each activation requires, as the database also checks it."""
    if activation == TierActivation.PAID and price_usd <= 0:
        raise ValueError("a paid Tier needs a price above zero")
    if activation in (TierActivation.FREE, TierActivation.NONE) and price_usd != 0:
        raise ValueError(f"the {activation.value} Tier costs nothing")
    if activation != TierActivation.PAID and monthly_usage_usd != 0:
        raise ValueError("only a paid Tier grants monthly usage")
    if activation == TierActivation.CONTACT and contact_url is None:
        raise ValueError("a contact-only Tier needs a contact link")
    if activation != TierActivation.NONE and agent_limit < 1:
        raise ValueError("a Tier must allow at least one Agent")
    if activation == TierActivation.NONE and (enabled or agent_limit != 0 or one_time_credit_usd != 0):
        raise ValueError("the none Tier is never offered and grants nothing")


# What the migration that created the catalog seeded, from the public pricing page. Kept
# here for tests that reset the catalog; the migration carries its own copy, as migrations do.
_EVERY_FEATURE = [feature.value for feature in TierFeature]
SEED_TIERS: tuple[dict[str, object], ...] = (
    {
        "id": UUID("00000000-0000-7000-8000-0000000071e0"),
        "key": FREE_TIER_KEY,
        "name": "Free",
        "tagline": "A premade agent on Telegram, and nothing else.",
        "activation": TierActivation.FREE,
        "sort_order": 10,
        "price_usd": Decimal(0),
        "price_note": None,
        "monthly_usage_usd": Decimal(0),
        "one_time_credit_usd": Decimal(10),
        "agent_limit": 1,
        "allowed_platform_keys": [CommunicationPlatform.AGENTBARN_TELEGRAM.value, CommunicationPlatform.WEB.value],
        "features": [TierFeature.TEAM.value],
        "contact_url": None,
    },
    {
        "id": UUID("00000000-0000-7000-8000-0000000071e1"),
        "key": "cloud_1",
        "name": "Cloud Tier 1",
        "tagline": "Full platform access with $20 of usage every month.",
        "activation": TierActivation.PAID,
        "sort_order": 20,
        "price_usd": Decimal(20),
        "price_note": "per month",
        "monthly_usage_usd": Decimal(20),
        "one_time_credit_usd": Decimal(10),
        "agent_limit": 1,
        "allowed_platform_keys": None,
        "features": [feature for feature in _EVERY_FEATURE if feature != TierFeature.PRIORITY_SUPPORT.value],
        "contact_url": None,
    },
    {
        "id": UUID("00000000-0000-7000-8000-0000000071e2"),
        "key": "cloud_2",
        "name": "Cloud Tier 2",
        "tagline": "Full platform access with $100 of usage every month.",
        "activation": TierActivation.PAID,
        "sort_order": 30,
        "price_usd": Decimal(100),
        "price_note": "per month",
        "monthly_usage_usd": Decimal(100),
        "one_time_credit_usd": Decimal(10),
        "agent_limit": 4,
        "allowed_platform_keys": None,
        "features": _EVERY_FEATURE,
        "contact_url": None,
    },
    {
        "id": UUID("00000000-0000-7000-8000-0000000071e3"),
        "key": "pilot",
        "name": "Supervised Pilot",
        "tagline": "One workflow scoped and put in front of real work over one week, with daily support.",
        "activation": TierActivation.CONTACT,
        "sort_order": 40,
        "price_usd": Decimal(500),
        "price_note": "per one-week pilot",
        "monthly_usage_usd": Decimal(0),
        "one_time_credit_usd": Decimal(0),
        "agent_limit": 4,
        "allowed_platform_keys": None,
        "features": _EVERY_FEATURE,
        "contact_url": "https://agentbarn.dev/pricing",
    },
    {
        "id": UUID("00000000-0000-7000-8000-0000000071ff"),
        "key": NONE_TIER_KEY,
        "name": "No tier",
        "tagline": "An Organization with no Tier it may use: no Agents, no features.",
        "activation": TierActivation.NONE,
        "sort_order": 1000,
        "price_usd": Decimal(0),
        "price_note": None,
        "monthly_usage_usd": Decimal(0),
        "one_time_credit_usd": Decimal(0),
        "agent_limit": 0,
        "allowed_platform_keys": [],
        "features": [],
        "contact_url": None,
    },
)
