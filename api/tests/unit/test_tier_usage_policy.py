"""TierUsagePolicy: the Tier's answer to the UsageGuard.

The integration tests cover each gated route; these cover the policy itself: every action
has a rule, each strategy, and the refusal every route returns.
"""

from typing import cast
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from hamcrest import assert_that, calling, equal_to, has_entries, is_, raises

from api.domains.templates.defaults import PREMADE_TEMPLATE_KEY
from api.domains.tiers.models import SEED_TIERS, Tier
from api.domains.tiers.usage_policy import _RULES, TierUsagePolicy
from api.domains.usage.guard import TemplateChoice, UsageAction, UsageSubject

TIERS = {str(seed["key"]): Tier.model_validate(seed) for seed in SEED_TIERS}
ORG = uuid4()
PREMADE = TemplateChoice(key=PREMADE_TEMPLATE_KEY, from_platform=True, agent_type="hermes")


def policy(tier_key: str | None, offered: tuple[str, ...] = ("free", "cloud_1", "cloud_2")) -> TierUsagePolicy:
    repository = Mock()
    repository.for_organization.return_value = TIERS[tier_key] if tier_key else None
    repository.list_offered.return_value = [TIERS[key] for key in offered]
    return TierUsagePolicy(repository=repository)


def refusal(
    tier_key: str,
    action: UsageAction,
    subject: UsageSubject | None = None,
    offered: tuple[str, ...] = ("free", "cloud_1", "cloud_2"),
) -> dict:
    with pytest.raises(HTTPException) as refused:
        policy(tier_key, offered).check(ORG, action, subject)
    assert_that(refused.value.status_code, equal_to(403))
    return cast(dict, refused.value.detail)


def test_every_action_has_a_rule():
    assert_that(set(_RULES), equal_to(set(UsageAction)))


# --- choosing a strategy ---------------------------------------------------------------------


@pytest.mark.parametrize("action", list(UsageAction))
def test_an_organization_without_a_tier_may_do_everything(action):
    subject = UsageSubject(platform_key="slack")

    assert_that(policy(None).allows(ORG, action, subject), is_(True))
    policy(None).check(ORG, action, subject)


@pytest.mark.parametrize("action", [action for action in UsageAction if action != UsageAction.BUY_CREDIT])
def test_the_none_tier_allows_nothing_new(action):
    assert_that(policy("none").allows(ORG, action, UsageSubject(platform_key="web")), is_(False))


# --- rules on a catalog tier -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "feature"),
    [
        (UsageAction.CUSTOMIZE_AGENT, "custom_agents"),
        (UsageAction.ADD_INTEGRATION, "integrations"),
        (UsageAction.CREATE_TEMPLATE, "templates_and_skills"),
        (UsageAction.CREATE_SKILL, "templates_and_skills"),
        (UsageAction.CREATE_PLAYBOOK, "templates_and_skills"),
        (UsageAction.CREATE_WORKFLOW, "workflows"),
        (UsageAction.RUN_WORKFLOW, "workflows"),
        (UsageAction.ENABLE_WEBHOOK, "agent_webhooks"),
        (UsageAction.ENABLE_MEMORY, "agent_memory"),
        (UsageAction.GRANT_MEMORY_ACCESS, "agent_memory"),
    ],
)
def test_a_feature_action_needs_its_feature(action, feature):
    assert_that(policy("cloud_1").allows(ORG, action), is_(True))
    assert_that(
        refusal("free", action),
        has_entries(code="TIER_FEATURE_UNAVAILABLE", feature=feature, platform=None, tier="free"),
    )


def test_inviting_needs_the_team_feature():
    assert_that(policy("free").allows(ORG, UsageAction.INVITE_MEMBER), is_(True))
    assert_that(policy("pilot").allows(ORG, UsageAction.INVITE_MEMBER), is_(True))
    assert_that(policy("none").allows(ORG, UsageAction.INVITE_MEMBER), is_(False))


@pytest.mark.parametrize("action", [UsageAction.CONNECT_CHANNEL, UsageAction.USE_CHANNEL])
def test_a_channel_needs_its_platform(action):
    assert_that(policy("free").allows(ORG, action, UsageSubject(platform_key="web")), is_(True))
    assert_that(policy("cloud_1").allows(ORG, action, UsageSubject(platform_key="slack")), is_(True))
    assert_that(
        refusal("free", action, UsageSubject(platform_key="slack")),
        has_entries(
            code="TIER_FEATURE_UNAVAILABLE",
            feature=None,
            platform="slack",
            message="Your organization's tier, Free, doesn't include Slack. It's available on Cloud Tier 1.",
        ),
    )


def test_a_channel_check_names_its_platform():
    assert_that(
        calling(policy("free").check).with_args(ORG, UsageAction.CONNECT_CHANNEL),
        raises(ValueError),
    )


@pytest.mark.parametrize("action", [UsageAction.HIRE_AGENT, UsageAction.REPIN_AGENT])
def test_without_custom_agents_only_the_premade_agent_is_hired(action):
    assert_that(policy("free").allows(ORG, action, UsageSubject(template=PREMADE)), is_(True))
    for other in (
        TemplateChoice(key="sales-assistant", from_platform=True, agent_type="hermes"),
        TemplateChoice(key=PREMADE_TEMPLATE_KEY, from_platform=False, agent_type="hermes"),
        TemplateChoice(key=PREMADE_TEMPLATE_KEY, from_platform=True, agent_type="openclaw"),
    ):
        assert_that(
            refusal("free", action, UsageSubject(template=other)),
            has_entries(code="TIER_FEATURE_UNAVAILABLE", feature="custom_agents"),
        )
    custom = TemplateChoice(key="sales-assistant", from_platform=False, agent_type="openclaw")
    assert_that(policy("cloud_1").allows(ORG, action, UsageSubject(template=custom)), is_(True))


@pytest.mark.parametrize(
    ("tier_key", "allowed"), [("free", False), ("none", False), ("cloud_1", True), ("pilot", True)]
)
def test_only_a_paid_or_contact_tier_buys_credit(tier_key, allowed):
    assert_that(policy(tier_key).allows(ORG, UsageAction.BUY_CREDIT), is_(allowed))


def test_buying_credit_on_free_says_to_subscribe():
    assert_that(
        refusal("free", UsageAction.BUY_CREDIT),
        equal_to({"code": "TIER_UPGRADE_REQUIRED", "message": "Subscribe to a paid tier to buy more credit."}),
    )


# --- where a refusal points --------------------------------------------------------------------


def test_a_refusal_points_to_the_first_offered_tier_that_allows_it():
    detail = refusal("free", UsageAction.CREATE_WORKFLOW)

    assert_that(
        detail,
        has_entries(
            message="Your organization's tier, Free, doesn't include workflows. It's available on Cloud Tier 1.",
            upgrade_tier={"key": "cloud_1", "name": "Cloud Tier 1"},
        ),
    )


def test_a_refusal_points_nowhere_when_no_offered_tier_allows_it():
    detail = refusal("free", UsageAction.CREATE_WORKFLOW, offered=("free",))

    assert_that(
        detail,
        has_entries(message="Your organization's tier, Free, doesn't include workflows.", upgrade_tier=None),
    )


def test_a_tier_that_runs_no_agents_is_never_suggested():
    detail = refusal("free", UsageAction.CREATE_WORKFLOW, offered=("none", "cloud_1"))

    assert_that(detail, has_entries(upgrade_tier={"key": "cloud_1", "name": "Cloud Tier 1"}))
