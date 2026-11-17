"""What other domains may read about an Organization's plan without knowing what decides it.

The shapes the Organization and Billing reads return, and the summary `UsageGuard` gives
them. The Tier catalog behind them stays in `api.domains.tiers`.
"""

import enum
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict


class TierActivation(str, enum.Enum):
    """How an Organization comes to be on a Tier."""

    # Granted at sign-up, once per inbox; the system's own Tier.
    FREE = "free"
    # Kept by a monthly subscription.
    PAID = "paid"
    # Assigned by a Platform Administrator after a conversation; never self-serve.
    CONTACT = "contact"
    # The system's Tier for an Organization that has none it may use.
    NONE = "none"


class OrganizationTierRead(PydanticBaseModel):
    """The Tier an Organization is on, as its members see it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    activation: TierActivation


class TierEntitlementsRead(PydanticBaseModel):
    """What an Organization's Tier lets it use. Without a Tier, everything."""

    features: list[str]
    # None: every Platform.
    allowed_platform_keys: list[str] | None


@dataclass(frozen=True)
class UsageSummary:
    """An Organization's plan for its reads."""

    tier: OrganizationTierRead | None
    entitlements: TierEntitlementsRead
    # The plan's Agent Limit, beneath the Organization's own; None when it sets none.
    agent_limit: int | None
    # Whether it already runs more than its plan covers. False unless asked for.
    over_limit: bool = False


class SuspensionReason(str, enum.Enum):
    """Why something an Organization has was switched off without being deleted."""

    # Its Tier no longer covers it.
    TIER = "tier"
