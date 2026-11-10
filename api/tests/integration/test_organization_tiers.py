"""An Organization on a Tier (Tiers, PR 2).

A Platform Administrator puts an Organization on a Tier, or takes it off any. Without a Tier
it is platform-managed and may use everything. On a Tier, its Agent Limit follows the Tier's
unless one was set for the Organization, and every gated action checks the Tier after
authorization: new or more use of what the Tier leaves out is refused with `403`
`TIER_FEATURE_UNAVAILABLE`, while what the Organization already has can still be read,
edited, disabled and deleted.
"""

import pytest
from fastapi import status
from hamcrest import assert_that, equal_to, has_entries, instance_of, is_, none, not_

from api.domains.organizations.repository import OrganizationRepository
from api.domains.rbac.catalog import OrganizationRole
from api.domains.templates.service import TemplateService
from api.domains.tiers.models import SEED_TIERS, TierFeature
from api.domains.tiers.repository import TierRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.helpers.workflows import authoring_is_enabled, draft
from api.tests.integration.test_agent_webhooks import _create_webhook
from api.tests.integration.test_spend_limits import events_named
from api.tests.integration.test_trial_organizations import the_organization_is_a_trial
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.events import event_delivery_tables_are_clean
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

TIER_IDS = {str(seed["key"]): seed["id"] for seed in SEED_TIERS}
EVERY_FEATURE = [feature.value for feature in TierFeature]


def _setup(*steps, default: str = ""):
    return [
        set_env_variable(
            {
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "LITELLM_BASE_URL": "http://litellm:4000",
                "LITELLM_SECRET_NAME": "litellm",
                "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
                "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
                "HERMES_IMAGE": "nousresearch/hermes-agent:v1.0",
                "ORGANIZATION_DEFAULT_AGENT_LIMIT": default,
            }
        ),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        event_delivery_tables_are_clean(),
        there_is_an_organization_with_user_and_access_token(),
        use_org_for_auth(),
        there_is_a_template(),
        lambda context: context.injector.get(TemplateService).seed_predefined_templates(),
        *steps,
    ]


def on_tier(key: str | None):
    def step(context):
        organizations = context.injector.get(OrganizationRepository)
        organization = organizations.get(context.organization.id)
        organization.tier_id = TIER_IDS[key] if key else None
        organizations.save(organization)

    return step


def tier_is_offered(key: str):
    def step(context):
        context.injector.get(TierRepository).update_with_events(TIER_IDS[key], {"enabled": True}, actor=_actor(context))

    return step


def _actor(context):
    from api.domains.tiers.repository import Actor

    return Actor(user_id=context.user.id, display="Platform Admin")


def owner_token_is_kept(context):
    context.owner_token = context.access_token


def a_platform_administrator_is_signed_in(context):
    owner_token_is_kept(context)
    there_is_a_user(email="platform@example.com", is_platform_admin=True, role=OrganizationRole.MEMBER)(context)
    there_is_an_access_token_for_user()(context)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def org_url(context, path: str = "") -> str:
    return f"/api/v1/organizations/{context.organization.id}{path}"


def agent_url(context, path: str = "") -> str:
    return org_url(context, f"/agents/{context.agent.id}{path}")


def assign(context, tier_key: str | None):
    return context.client.put(
        f"/api/v1/platform/organizations/{context.organization.id}/tier",
        json={"tier_id": str(TIER_IDS[tier_key]) if tier_key else None},
        headers=auth(context.access_token),
    )


def read_organization(context, token: str | None = None):
    return context.client.get(org_url(context), headers=auth(token or context.access_token)).json()


def hire(context, template_key: str = "test-template", agent_type: str = "openclaw", **extra):
    return context.client.post(
        org_url(context, "/agents"),
        json={"name": "Hire", "template_key": template_key, "agent_type": agent_type, **extra},
        headers=auth(context.access_token),
    )


def refused_by_tier(response, **expected) -> None:
    assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN), response.text)
    assert_that(response.json()["detail"], has_entries(code="TIER_FEATURE_UNAVAILABLE", **expected))


# --- a Platform Administrator assigns it -------------------------------------------------


def test_a_platform_administrator_puts_an_organization_on_a_tier():
    with given(_setup(a_platform_administrator_is_signed_in)) as context:
        with when("they put it on Free"):
            response = assign(context, "free")

        with then("it is on Free, chosen by the platform, and the change is audited"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(
                response.json(),
                has_entries(
                    tier_id=str(TIER_IDS["free"]),
                    tier_assigned_by_platform=True,
                    tier=has_entries(key="free", name="Free", activation="free"),
                ),
            )
            (event,) = events_named(context, "organization.tier.changed")
            assert_that(event.payload, has_entries(tier_key="free", previous_tier_key=None, assigned_by_platform=True))


def test_taking_an_organization_off_its_tier_leaves_it_unrestricted():
    with given(_setup(on_tier("free"), a_platform_administrator_is_signed_in)) as context:
        response = assign(context, None)

        assert_that(response.json(), has_entries(tier_id=None, tier=None, tier_assigned_by_platform=False))
        (event,) = events_named(context, "organization.tier.changed")
        assert_that(event.payload, has_entries(tier_key=None, previous_tier_key="free"))


def test_assigning_the_tier_it_is_already_on_records_nothing():
    with given(_setup(on_tier("free"), a_platform_administrator_is_signed_in)) as context:
        response = assign(context, "free")

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(events_named(context, "organization.tier.changed"), equal_to([]))


def test_a_tier_that_does_not_exist_is_refused():
    with given(_setup(a_platform_administrator_is_signed_in)) as context:
        response = context.client.put(
            f"/api/v1/platform/organizations/{context.organization.id}/tier",
            json={"tier_id": "00000000-0000-7000-8000-000000000000"},
            headers=auth(context.access_token),
        )

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))


def test_an_organization_owner_cannot_choose_its_tier():
    with given(_setup()) as context:
        response = assign(context, "cloud_2")

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_tier_organizations_are_on_cannot_be_deleted():
    with given(_setup(a_platform_administrator_is_signed_in)) as context:
        created = context.client.post(
            "/api/v1/platform/tiers",
            json={
                "key": "comped",
                "name": "Comped",
                "activation": "contact",
                "price_usd": "0",
                "agent_limit": 2,
                "contact_url": "https://agentbarn.dev/pricing",
            },
            headers=auth(context.access_token),
        ).json()
        context.client.put(
            f"/api/v1/platform/organizations/{context.organization.id}/tier",
            json={"tier_id": created["id"]},
            headers=auth(context.access_token),
        )

        response = context.client.delete(f"/api/v1/platform/tiers/{created['id']}", headers=auth(context.access_token))

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT), response.text)


# --- the Agent Limit ------------------------------------------------------------------------


def test_the_tiers_agent_limit_replaces_the_default():
    with given(_setup(on_tier("cloud_2"), default="1")) as context:
        assert_that(read_organization(context), has_entries(agent_limit=4))


def test_the_none_tier_allows_no_agents():
    with given(_setup(on_tier("none"))) as context:
        response = hire(context, "general-purpose", "hermes")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT), response.text)
        assert_that(read_organization(context), has_entries(agent_limit=0, agent_limit_reached=True))


def test_an_organizations_own_limit_beats_its_tiers():
    def own_limit(context):
        organizations = context.injector.get(OrganizationRepository)
        organization = organizations.get(context.organization.id)
        organization.agent_limit = 2
        organizations.save(organization)

    with given(_setup(on_tier("free"), own_limit)) as context:
        assert_that(read_organization(context), has_entries(agent_limit=2))


def test_a_trials_tier_beats_the_trial_setting():
    with given(_setup(the_organization_is_a_trial(), on_tier("cloud_2"))) as context:
        assert_that(read_organization(context), has_entries(agent_limit=4, trial_agent_limit=4))


# --- the Organization read -------------------------------------------------------------


def test_without_a_tier_the_read_allows_everything():
    with given(_setup()) as context:
        assert_that(
            read_organization(context),
            has_entries(
                tier=None,
                entitlements=has_entries(features=EVERY_FEATURE, allowed_platform_keys=None),
                over_tier=False,
            ),
        )


def test_on_free_the_read_gives_its_tier_and_what_it_allows():
    with given(_setup(on_tier("free"))) as context:
        assert_that(
            read_organization(context),
            has_entries(
                tier=has_entries(key="free", name="Free"),
                entitlements=has_entries(features=["team"], allowed_platform_keys=["agentbarn_telegram", "web"]),
                over_tier=False,
            ),
        )


def test_running_more_than_the_tier_covers_is_over_tier():
    with given(_setup(there_is_an_agent(name="One"), there_is_an_agent(name="Two"))) as context:
        on_tier("free")(context)

        with when("the Organization is read, by its members and by the platform"):
            member_read = read_organization(context)
            a_platform_administrator_is_signed_in(context)
            platform_read = context.client.get(
                f"/api/v1/platform/organizations/{context.organization.id}", headers=auth(context.access_token)
            ).json()

        with then("both say it runs more than Free covers"):
            assert_that(member_read, has_entries(over_tier=True))
            assert_that(platform_read, has_entries(over_tier=True, agent_limit_in_force=1))


# --- gated actions ---------------------------------------------------------------------


def test_free_hires_only_the_premade_agent():
    with given(_setup(on_tier("free"))) as context:
        with when("the owner hires a custom Agent, then the premade one"):
            custom = hire(context)
            premade = hire(context, "general-purpose", "hermes")

        with then("only the premade Agent is hired"):
            refused_by_tier(custom, feature="custom_agents", tier="free", upgrade_tier=None)
            assert_that(premade.status_code, equal_to(status.HTTP_201_CREATED), premade.text)


def test_a_refusal_names_the_first_offered_tier_that_allows_it():
    with given(_setup(on_tier("free"), tier_is_offered("cloud_2"), tier_is_offered("cloud_1"))) as context:
        response = hire(context)

        refused_by_tier(response, upgrade_tier={"key": "cloud_1", "name": "Cloud Tier 1"})
        assert_that(
            response.json()["detail"]["message"],
            equal_to("Your organization's tier, Free, doesn't include custom agents. It's available on Cloud Tier 1."),
        )


def test_the_premade_agent_on_openclaw_is_a_custom_agent():
    with given(_setup(on_tier("free"))) as context:
        refused_by_tier(hire(context, "general-purpose", "openclaw"), feature="custom_agents")


def test_without_a_tier_any_agent_may_be_hired():
    with given(_setup()) as context:
        assert_that(hire(context).status_code, equal_to(status.HTTP_201_CREATED))


def test_platforms_free_leaves_out_are_not_listed_or_connected():
    with given(_setup(on_tier("free"), there_is_an_agent())) as context:
        with when("the owner lists Platforms and connects Slack"):
            listed = context.client.get(
                org_url(context, "/communication-platforms"), headers=auth(context.access_token)
            )
            connected = context.client.post(
                agent_url(context, "/connections"),
                json={"platform_key": "slack", "display_name": "Slack", "settings": {}, "credentials": {}},
                headers=auth(context.access_token),
            )

        with then("Slack is neither listed nor connected"):
            assert_that("slack" in [platform["key"] for platform in listed.json()], is_(False))
            refused_by_tier(connected, platform="slack", feature=None)


def test_web_chat_is_refused_when_the_tier_leaves_it_out():
    def free_without_web_chat(context):
        context.injector.get(TierRepository).update_with_events(
            TIER_IDS["free"], {"allowed_platform_keys": ["agentbarn_telegram"]}, actor=_actor(context)
        )

    with given(_setup(free_without_web_chat, on_tier("free"), there_is_an_agent())) as context:
        response = context.client.post(
            agent_url(context, "/web-chat/messages"), json={"text": "Hello"}, headers=auth(context.access_token)
        )

        refused_by_tier(response, platform="web")


def _gated_requests():
    jira = {"site_url": "https://test.atlassian.net", "email": "admin@example.com", "api_token": "token"}
    return {
        "shared credential": lambda c: c.client.post(
            org_url(c, "/shared-credentials"),
            json={"provider": "jira", "name": "Jira", "content": jira},
            headers=auth(c.access_token),
        ),
        "custom api": lambda c: c.client.post(
            agent_url(c, "/custom-api-connections"),
            json={"name": "Inventory", "base_url": "https://api.example.com/v1", "auth": {"type": "none"}},
            headers=auth(c.access_token),
        ),
        "agent credentials": lambda c: hire(
            c, "general-purpose", "hermes", secrets=[{"provider": "jira", "content": jira}]
        ),
        "organization template": lambda c: c.client.post(
            org_url(c, "/templates"), json={"template_name": "Mine", "soul_md": "soul"}, headers=auth(c.access_token)
        ),
        "organization skill": lambda c: c.client.post(
            org_url(c, "/skills"),
            json={"name": "Mine", "files": [{"path": "SKILL.md", "content": "# Skill"}]},
            headers=auth(c.access_token),
        ),
        "workflow": lambda c: c.client.post(agent_url(c, "/workflows"), json=draft(), headers=auth(c.access_token)),
        "agent webhook": lambda c: c.client.post(
            agent_url(c, "/webhooks"),
            json={"display_name": "Hook", "delivery_platform": "slack"},
            headers=auth(c.access_token),
        ),
        "agent memory": lambda c: c.client.put(
            agent_url(c, "/memory"), json={"enabled": True}, headers=auth(c.access_token)
        ),
        "memory grant": lambda c: c.client.post(
            org_url(c, "/memory-grants"), json={"agent_id": str(c.agent.id)}, headers=auth(c.access_token)
        ),
    }


_FEATURE_OF = {
    "shared credential": "integrations",
    "custom api": "integrations",
    "agent credentials": "integrations",
    "organization template": "templates_and_skills",
    "organization skill": "templates_and_skills",
    "workflow": "workflows",
    "agent webhook": "agent_webhooks",
    "agent memory": "agent_memory",
    "memory grant": "agent_memory",
}


@pytest.mark.parametrize("action", list(_FEATURE_OF))
def test_free_refuses_what_it_leaves_out(action):
    with given(_setup(on_tier("free"), there_is_an_agent(), authoring_is_enabled)) as context:
        response = _gated_requests()[action](context)

        refused_by_tier(response, feature=_FEATURE_OF[action])


def test_free_may_invite_teammates_but_the_none_tier_may_not():
    def invite(context, email):
        return context.client.post(
            org_url(context, "/members"), json={"email": email}, headers=auth(context.access_token)
        )

    with given(_setup(on_tier("free"))) as context:
        on_free = invite(context, "teammate@example.com")
        on_tier("none")(context)
        on_none = invite(context, "another@example.com")

        assert_that(on_free.status_code, equal_to(status.HTTP_201_CREATED), on_free.text)
        refused_by_tier(on_none, feature="team", tier="none")


def test_authorization_is_checked_before_the_tier():
    def a_member_is_signed_in(context):
        there_is_a_user(email="member@example.com", role=OrganizationRole.MEMBER)(context)
        there_is_an_access_token_for_user()(context)

    with given(_setup(on_tier("free"), a_member_is_signed_in)) as context:
        response = context.client.post(
            org_url(context, "/templates"),
            json={"template_name": "Mine", "soul_md": "soul"},
            headers=auth(context.access_token),
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(response.json()["detail"], instance_of(str))


def test_what_an_organization_already_has_can_be_disabled_and_deleted_but_not_re_enabled():
    with given(_setup(there_is_an_agent())) as context:
        created = _create_webhook(context)
        on_tier("free")(context)
        webhook = agent_url(context, f"/webhooks/{created['id']}")

        with when("the owner disables it, tries to enable it again, then deletes it"):
            disabled = context.client.patch(
                webhook, json={"enabled": False, "revision": created["revision"]}, headers=auth(context.access_token)
            )
            enabled = context.client.patch(
                webhook,
                json={"enabled": True, "revision": disabled.json()["revision"]},
                headers=auth(context.access_token),
            )
            deleted = context.client.delete(
                f"{webhook}?revision={disabled.json()['revision']}", headers=auth(context.access_token)
            )

        with then("disabling and deleting work; enabling is refused"):
            assert_that(disabled.status_code, equal_to(status.HTTP_200_OK), disabled.text)
            refused_by_tier(enabled, feature="agent_webhooks")
            assert_that(deleted.status_code, equal_to(status.HTTP_204_NO_CONTENT), deleted.text)


def test_memory_can_be_turned_off_without_the_feature():
    def memory_is_on(context):
        from sqlmodel import Session

        from api.domains.agents.models import Agent
        from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            agent = session.get_one(Agent, context.agent.id)
            agent.memory_enabled = True
            session.add(agent)
            session.commit()

    with given(_setup(there_is_an_agent(), memory_is_on, on_tier("free"))) as context:
        assert_that(read_organization(context), has_entries(over_tier=True))

        response = context.client.put(
            agent_url(context, "/memory"), json={"enabled": False}, headers=auth(context.access_token)
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(read_organization(context), has_entries(over_tier=False, tier=not_(none())))
