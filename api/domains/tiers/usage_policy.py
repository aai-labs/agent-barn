"""The Tier's answer to `UsageGuard`: the one place that decides what an Organization's Tier
lets it start using.

It also gives other domains' reads their `UsageSummary`. No Tier is unrestricted; any Tier
is checked against its catalog row (the none Tier's row allows nothing). Each action has
one rule (a feature, a Platform, the premade Agent, or a paid Tier), so a new action is a
row in `_RULES` rather than a check in another domain.
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
    agent_limit_in_force,
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


@inject
@singleton
@dataclass
class TierUsagePolicy(UsageGuard):
    repository: TierRepository

    """No Tier is unrestricted: the Organization is platform-managed. Any Tier, the none Tier
    included, allows what its catalog row does, by each action's rule in `_RULES`."""

    def allows(self, organization_id: UUID, action: UsageAction, subject: UsageSubject | None = None) -> bool:
        tier = self.repository.for_organization(organization_id)
        return tier is None or _RULES[action].allowed(tier, subject or UsageSubject())

    def check(self, organization_id: UUID, action: UsageAction, subject: UsageSubject | None = None) -> None:
        subject = subject or UsageSubject()
        tier = self.repository.for_organization(organization_id)
        rule = _RULES[action]
        if tier is None or rule.allowed(tier, subject):
            return
        upgrade = next((offered for offered in self._upgrades() if rule.allowed(offered, subject)), None)
        raise rule.refusal(tier, subject, upgrade)

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

    def _upgrades(self) -> list[Tier]:
        """Offered Tiers that run Agents, in catalog order: where a refusal points."""
        return [tier for tier in self.repository.list_offered() if tier.agent_limit > 0]


def is_over_tier(tier: Tier, coverage: TierCoverage) -> bool:
    """Whether the Organization already runs more than its Tier covers. Agents are counted
    against the limit in force, the Organization's own limit before its Tier's, as holds are."""
    return (
        coverage.agents > agent_limit_in_force(coverage.own_agent_limit, tier)
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
