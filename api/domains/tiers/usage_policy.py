"""The Tier's answer to `UsageGuard`: the one place that decides what an Organization's Tier
lets it start using.

It also gives other domains' reads their `UsageSummary`. For a check, it loads the
Organization's Tier and chooses a strategy for it: no Tier is unrestricted, and
any Tier is checked against its catalog row (the none Tier's row allows nothing). Inside
a strategy, each action has one rule (a feature, a Platform, the premade Agent, or a paid
Tier), so a new action is a row in `_RULES` rather than a check in another domain.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.templates.defaults import PREMADE_TEMPLATE_KEY
from api.domains.tiers.models import (
    Tier,
    TierActivation,
    TierFeature,
    allows_feature,
    allows_platform,
)
from api.domains.tiers.repository import TierCoverage, TierRepository
from api.domains.usage.guard import UsageAction, UsageGuard, UsageSubject
from api.domains.usage.models import OrganizationTierRead, TierEntitlementsRead, UsageSummary

TIER_FEATURE_UNAVAILABLE = "TIER_FEATURE_UNAVAILABLE"
TIER_UPGRADE_REQUIRED = "TIER_UPGRADE_REQUIRED"
# The premade Agent runs on Hermes.
_PREMADE_AGENT_TYPE = "hermes"

_FEATURE_LABELS = {
    TierFeature.CUSTOM_AGENTS: "custom agents",
    TierFeature.INTEGRATIONS: "integrations",
    TierFeature.TEMPLATES_AND_SKILLS: "templates and skills",
    TierFeature.WORKFLOWS: "workflows",
    TierFeature.AGENT_WEBHOOKS: "agent webhooks",
    TierFeature.AGENT_MEMORY: "agent memory",
    TierFeature.TEAM: "inviting teammates",
    TierFeature.PRIORITY_SUPPORT: "priority support",
}
_PLATFORM_LABELS = {
    "slack": "Slack",
    "teams": "Microsoft Teams",
    "telegram": "Telegram",
    "agentbarn_telegram": "Agent Barn Telegram",
    "discord": "Discord",
    "web": "Web Chat",
    "email": "email",
}


# --- rules: what one action needs from a Tier ----------------------------------------------


class _Rule(ABC):
    @abstractmethod
    def allowed(self, tier: Tier, subject: UsageSubject) -> bool: ...

    @abstractmethod
    def refusal(self, tier: Tier, subject: UsageSubject, upgrade: Tier | None) -> HTTPException: ...


@dataclass(frozen=True)
class _Feature(_Rule):
    feature: TierFeature

    def allowed(self, tier: Tier, subject: UsageSubject) -> bool:
        return allows_feature(tier, self.feature)

    def refusal(self, tier: Tier, subject: UsageSubject, upgrade: Tier | None) -> HTTPException:
        return _unavailable(tier, _FEATURE_LABELS[self.feature], upgrade, feature=self.feature.value)


class _Platform(_Rule):
    def allowed(self, tier: Tier, subject: UsageSubject) -> bool:
        return allows_platform(tier, _platform_key(subject))

    def refusal(self, tier: Tier, subject: UsageSubject, upgrade: Tier | None) -> HTTPException:
        key = _platform_key(subject)
        return _unavailable(tier, _PLATFORM_LABELS.get(key, key), upgrade, platform=key)


class _PremadeOrCustomAgents(_Rule):
    """Without custom agents, an Organization runs only the premade Agent."""

    _custom = _Feature(TierFeature.CUSTOM_AGENTS)

    def allowed(self, tier: Tier, subject: UsageSubject) -> bool:
        template = subject.template
        premade = (
            template is not None
            and template.from_platform
            and template.key == PREMADE_TEMPLATE_KEY
            and template.agent_type == _PREMADE_AGENT_TYPE
        )
        return premade or self._custom.allowed(tier, subject)

    def refusal(self, tier: Tier, subject: UsageSubject, upgrade: Tier | None) -> HTTPException:
        return self._custom.refusal(tier, subject, upgrade)


class _PaidTier(_Rule):
    """Free and none don't buy credit: they subscribe to a paid Tier first."""

    def allowed(self, tier: Tier, subject: UsageSubject) -> bool:
        return tier.activation not in (TierActivation.FREE, TierActivation.NONE)

    def refusal(self, tier: Tier, subject: UsageSubject, upgrade: Tier | None) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": TIER_UPGRADE_REQUIRED, "message": "Subscribe to a paid tier to buy more credit."},
        )


_TEMPLATES_AND_SKILLS = _Feature(TierFeature.TEMPLATES_AND_SKILLS)
_WORKFLOWS = _Feature(TierFeature.WORKFLOWS)
_AGENT_MEMORY = _Feature(TierFeature.AGENT_MEMORY)

_RULES: dict[UsageAction, _Rule] = {
    UsageAction.HIRE_AGENT: _PremadeOrCustomAgents(),
    UsageAction.REPIN_AGENT: _PremadeOrCustomAgents(),
    UsageAction.CUSTOMIZE_AGENT: _Feature(TierFeature.CUSTOM_AGENTS),
    UsageAction.ADD_INTEGRATION: _Feature(TierFeature.INTEGRATIONS),
    UsageAction.CONNECT_CHANNEL: _Platform(),
    UsageAction.USE_CHANNEL: _Platform(),
    UsageAction.CREATE_TEMPLATE: _TEMPLATES_AND_SKILLS,
    UsageAction.CREATE_SKILL: _TEMPLATES_AND_SKILLS,
    UsageAction.CREATE_PLAYBOOK: _TEMPLATES_AND_SKILLS,
    UsageAction.CREATE_WORKFLOW: _WORKFLOWS,
    UsageAction.RUN_WORKFLOW: _WORKFLOWS,
    UsageAction.ENABLE_WEBHOOK: _Feature(TierFeature.AGENT_WEBHOOKS),
    UsageAction.ENABLE_MEMORY: _AGENT_MEMORY,
    UsageAction.GRANT_MEMORY_ACCESS: _AGENT_MEMORY,
    UsageAction.INVITE_MEMBER: _Feature(TierFeature.TEAM),
    UsageAction.BUY_CREDIT: _PaidTier(),
}


# --- strategies: how an Organization's Tier is checked ----------------------------------------


class _Strategy(ABC):
    @abstractmethod
    def allows(self, rule: _Rule, subject: UsageSubject) -> bool: ...

    @abstractmethod
    def refusal(self, rule: _Rule, subject: UsageSubject, upgrades: list[Tier]) -> HTTPException: ...


class _Unrestricted(_Strategy):
    """No Tier: the Organization is platform-managed and may use everything."""

    def allows(self, rule: _Rule, subject: UsageSubject) -> bool:
        return True

    def refusal(self, rule: _Rule, subject: UsageSubject, upgrades: list[Tier]) -> HTTPException:
        raise AssertionError("an unrestricted Organization is never refused")


@dataclass(frozen=True)
class _CatalogTier(_Strategy):
    """What the Tier's catalog row allows."""

    tier: Tier

    def allows(self, rule: _Rule, subject: UsageSubject) -> bool:
        return rule.allowed(self.tier, subject)

    def refusal(self, rule: _Rule, subject: UsageSubject, upgrades: list[Tier]) -> HTTPException:
        upgrade = next((tier for tier in upgrades if rule.allowed(tier, subject)), None)
        return rule.refusal(self.tier, subject, upgrade)


@inject
@singleton
@dataclass
class TierUsagePolicy(UsageGuard):
    repository: TierRepository

    def allows(self, organization_id: UUID, action: UsageAction, subject: UsageSubject | None = None) -> bool:
        return self._strategy(organization_id).allows(_RULES[action], subject or UsageSubject())

    def check(self, organization_id: UUID, action: UsageAction, subject: UsageSubject | None = None) -> None:
        subject = subject or UsageSubject()
        strategy = self._strategy(organization_id)
        rule = _RULES[action]
        if not strategy.allows(rule, subject):
            raise strategy.refusal(rule, subject, self._upgrades())

    def summary(self, organization_id: UUID, *, coverage: bool = False) -> UsageSummary:
        tier = self.repository.for_organization(organization_id)
        if tier is None:
            every_feature = [feature.value for feature in TierFeature]
            return UsageSummary(
                tier=None,
                entitlements=TierEntitlementsRead(features=every_feature, allowed_platform_keys=None),
                agent_limit=None,
            )
        return UsageSummary(
            tier=OrganizationTierRead.model_validate(tier),
            entitlements=TierEntitlementsRead(
                features=list(tier.features), allowed_platform_keys=tier.allowed_platform_keys
            ),
            agent_limit=tier.agent_limit,
            over_limit=coverage and is_over_tier(tier, self.repository.coverage(organization_id)),
        )

    def _strategy(self, organization_id: UUID) -> _Strategy:
        tier = self.repository.for_organization(organization_id)
        return _Unrestricted() if tier is None else _CatalogTier(tier)

    def _upgrades(self) -> list[Tier]:
        """Offered Tiers that run Agents, in catalog order: where a refusal points."""
        return [tier for tier in self.repository.list_offered() if tier.agent_limit > 0]


def is_over_tier(tier: Tier, coverage: TierCoverage) -> bool:
    """Whether the Organization already runs more than its Tier covers."""
    return (
        coverage.agents > tier.agent_limit
        or any(not allows_platform(tier, key) for key in coverage.enabled_platform_keys)
        or (coverage.memory_agents > 0 and not allows_feature(tier, TierFeature.AGENT_MEMORY))
        or (coverage.enabled_webhooks > 0 and not allows_feature(tier, TierFeature.AGENT_WEBHOOKS))
    )


def _platform_key(subject: UsageSubject) -> str:
    if subject.platform_key is None:
        raise ValueError("connecting a channel names its Platform")
    return subject.platform_key


def _unavailable(
    tier: Tier, label: str, upgrade: Tier | None, *, feature: str | None = None, platform: str | None = None
) -> HTTPException:
    message = f"Your organization's tier, {tier.name}, doesn't include {label}."
    if upgrade is not None:
        message += f" It's available on {upgrade.name}."
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": TIER_FEATURE_UNAVAILABLE,
            "message": message,
            "feature": feature,
            "platform": platform,
            "tier": tier.key,
            "upgrade_tier": {"key": upgrade.key, "name": upgrade.name} if upgrade is not None else None,
        },
    )
