"""Tier Holds (Tiers, PR 3).

When an Organization's Tier stops covering what it runs, the newest Agents beyond the Agent
Limit are held and stopped, and Connections, Agent Memory and Agent Webhooks the Tier leaves
out are switched off. Nothing is deleted. Owners and Admins swap which Agents stay held, and
release held items once the Tier covers them again; nothing is released automatically.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import status
from hamcrest import (
    assert_that,
    contains_inanyorder,
    equal_to,
    has_entries,
    has_item,
    has_length,
    has_properties,
    is_,
    none,
    not_none,
)

from api.domains.agent_webhooks.models import AgentWebhook
from api.domains.agents.models import Agent, AgentStatus
from api.domains.agents.service import AgentService
from api.domains.communications.models import CommunicationConnection
from api.domains.events import ActorIdentity, ActorIdentityType
from api.domains.rbac.catalog import OrganizationRole
from api.domains.subscriptions.service import SubscriptionService
from api.domains.tiers.repository import Actor, TierRepository
from api.domains.usage.models import SuspensionReason
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.integration.test_agent_webhooks import _create_webhook, _ensure_native_connection
from api.tests.integration.test_organization_tiers import (
    TIER_IDS,
    _setup,
    a_platform_administrator_is_signed_in,
    agent_url,
    assign,
    auth,
    hire,
    read_organization,
)
from api.tests.integration.test_spend_limits import events_named
from api.tests.steps.agent import there_is_an_agent
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

SYSTEM = ActorIdentity(type=ActorIdentityType.SYSTEM, id="test")


def agents_named(*names: str, status: AgentStatus = AgentStatus.STOPPED):
    """Agents created oldest first, kept on the context by name."""

    def step(context):
        context.agents = getattr(context, "agents", {})
        for name in names:
            there_is_an_agent(name=name, status=status)(context)
            context.agents[name] = context.agent

    return step


def stored(context, agent_name: str) -> Agent:
    from sqlmodel import Session

    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return session.get_one(Agent, context.agents[agent_name].id)


def connections_of(context) -> list[CommunicationConnection]:
    from sqlmodel import Session, select

    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return list(
            session.exec(
                select(CommunicationConnection).where(CommunicationConnection.agent_id == context.agent.id)
            ).all()
        )


def webhooks_of(context) -> list[AgentWebhook]:
    from sqlmodel import Session, select

    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return list(session.exec(select(AgentWebhook).where(AgentWebhook.agent_id == context.agent.id)).all())


def has_properties_of(**expected):
    return has_properties(**expected)


def holds_url(context, path: str = "") -> str:
    return f"/api/v1/organizations/{context.organization.id}/tier-holds{path}"


def as_owner(context) -> dict:
    return auth(context.owner_token)


def put_on(context, tier_key: str):
    """A Platform Administrator puts the Organization on a Tier, keeping the owner's token."""
    if not hasattr(context, "owner_token"):
        a_platform_administrator_is_signed_in(context)
    response = assign(context, tier_key)
    assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
    return response


# --- holds apply when coverage drops -----------------------------------------------------


def test_a_lower_tier_holds_and_stops_the_newest_agents():
    with given(_setup(agents_named("Oldest", "Newest", status=AgentStatus.RUNNING))) as context:
        with when("a Platform Administrator puts the Organization on Free"):
            put_on(context, "free")

        with then("the oldest Agent is kept, the newest is held and stopped, and it's audited"):
            assert_that(stored(context, "Oldest"), has_properties_of(suspended_at=None, status=AgentStatus.RUNNING))
            newest = stored(context, "Newest")
            assert_that(newest.suspended_at, is_(not_none()))
            assert_that(newest.status, equal_to(AgentStatus.STOPPED))
            (event,) = events_named(context, "organization.tier_holds.changed")
            assert_that(
                event.payload,
                has_entries(reason="tier", held_agent_ids=[str(context.agents["Newest"].id)], released_agent_ids=[]),
            )
            assert_that(read_organization(context, context.owner_token), has_entries(over_tier=False))


def test_a_held_agent_cannot_start():
    with given(_setup(agents_named("Oldest", "Newest"))) as context:
        put_on(context, "free")
        context.agent = context.agents["Newest"]

        response = context.client.post(agent_url(context, "/start"), headers=as_owner(context))

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT), response.text)
        assert_that(response.json()["detail"], has_entries(code="AGENT_SUSPENDED", reason="tier"))


def test_a_hold_that_lands_while_an_agent_starts_stops_it_once_started(monkeypatch):
    with given(_setup(agents_named("Starting"))) as context:
        context.agent = context.agents["Starting"]
        service = context.injector.get(AgentService)
        provision = service._provision_and_start

        def held_while_provisioning(agent, preflight=False):
            started = provision(agent, preflight=preflight)
            if not preflight:
                context.injector.get(TierRepository).hold_agent(
                    context.organization.id, agent.id, actor=SYSTEM, actor_display="Tier change"
                )
            return started

        monkeypatch.setattr(service, "_provision_and_start", held_while_provisioning)

        with when("the Agent is held while it starts"):
            response = context.client.post(agent_url(context, "/start"), headers=auth(context.access_token))

        with then("the start finishes, then stops it"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(response.json(), has_entries(status="STOPPED", suspension_reason="tier"))
            assert_that(stored(context, "Starting").status, equal_to(AgentStatus.STOPPED))


def test_the_tier_sweep_stops_a_held_agent_still_running():
    with given(_setup(agents_named("Oldest", "Newest", status=AgentStatus.RUNNING))) as context:
        put_on(context, "free")
        # A stop the hold couldn't make, because another lifecycle operation held the lock.
        newest = stored(context, "Newest")
        newest.status = AgentStatus.RUNNING
        context.injector.get(PostgresRepositoryDelegate).save(newest)

        context.injector.get(SubscriptionService).sweep()

        assert_that(stored(context, "Newest").status, equal_to(AgentStatus.STOPPED))
        assert_that(stored(context, "Oldest").status, equal_to(AgentStatus.RUNNING))


def test_a_held_agent_takes_no_place_but_the_limit_still_holds():
    with given(_setup(agents_named("Oldest", "Newest"))) as context:
        put_on(context, "free")
        context.access_token = context.owner_token

        response = hire(context, "general-purpose", "hermes")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT), response.text)
        assert_that(read_organization(context), has_entries(agent_limit=1, agent_limit_reached=True))


def test_connections_memory_and_webhooks_the_tier_leaves_out_are_switched_off():
    def connections_memory_and_a_webhook(context):
        _ensure_native_connection(context, "slack")
        _ensure_native_connection(context, "telegram")
        from sqlmodel import Session

        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            agent = session.get_one(Agent, context.agent.id)
            agent.memory_enabled = True
            session.add(agent)
            session.commit()
        context.client.post(
            agent_url(context, "/webhooks"),
            json={"display_name": "Hook", "delivery_platform": "slack"},
            headers=auth(context.access_token),
        )

    with given(_setup(agents_named("Only"), connections_memory_and_a_webhook)) as context:
        with when("the Organization is put on Free"):
            put_on(context, "free")

        with then("each is off and held, and nothing is deleted"):
            connections = connections_of(context)
            assert_that(
                [(c.platform_key, c.enabled, c.suspended_at is not None) for c in connections],
                contains_inanyorder(("slack", False, True), ("telegram", False, True)),
            )
            assert_that(stored(context, "Only"), has_properties_of(memory_enabled=False))
            assert_that(stored(context, "Only").memory_suspended_at, is_(not_none()))
            (webhook,) = webhooks_of(context)
            assert_that((webhook.enabled, webhook.suspended_at is not None), equal_to((False, True)))
            holds = context.client.get(holds_url(context), headers=as_owner(context)).json()
            assert_that(holds["connections"], has_length(2))
            assert_that(holds["memory"], has_length(1))
            assert_that(holds["webhooks"], has_length(1))


def test_a_kept_running_agent_restarts_without_its_held_native_channel():
    def with_slack(context):
        _ensure_native_connection(context, "slack")

    with given(_setup(agents_named("Only", status=AgentStatus.RUNNING), with_slack)) as context:
        with when("the Organization is put on Free, which leaves Slack out"):
            put_on(context, "free")

        with then("the Agent is kept and restarted, so its runtime drops Slack"):
            assert_that(stored(context, "Only"), has_properties_of(suspended_at=None, status=AgentStatus.RUNNING))
            assert_that(events_named(context, "agent.stopped"), has_length(1))
            assert_that(events_named(context, "agent.started"), has_length(1))


def test_a_native_channel_held_while_its_agent_starts_restarts_it(monkeypatch):
    with given(_setup(agents_named("Starting"))) as context:
        context.agent = context.agents["Starting"]
        # Switched off already, so the start needs no real Slack credentials; what counts is
        # that it is suspended while the Agent starts.
        _ensure_native_connection(context, "slack")
        (slack,) = connections_of(context)
        slack.enabled = False
        context.injector.get(PostgresRepositoryDelegate).save(slack)
        service = context.injector.get(AgentService)
        provision = service._provision_and_start
        starts: list[UUID] = []

        def slack_held_while_provisioning(agent, preflight=False):
            started = provision(agent, preflight=preflight)
            if not preflight:
                starts.append(agent.id)
                if len(starts) == 1:
                    (slack,) = connections_of(context)
                    slack.suspend(SuspensionReason.TIER, datetime.now(UTC))
                    context.injector.get(PostgresRepositoryDelegate).save(slack)
            return started

        monkeypatch.setattr(service, "_provision_and_start", slack_held_while_provisioning)

        with when("Slack is held while the Agent starts"):
            response = context.client.post(agent_url(context, "/start"), headers=auth(context.access_token))

        with then("it starts again without it"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(response.json(), has_entries(status="RUNNING"))
            assert_that(starts, has_length(2))


def test_an_agent_already_held_loses_what_a_lower_tier_leaves_out():
    def newest_has_slack_and_memory(context):
        context.agent = context.agents["Newest"]
        _ensure_native_connection(context, "slack")
        from sqlmodel import Session

        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            agent = session.get_one(Agent, context.agent.id)
            agent.memory_enabled = True
            session.add(agent)
            session.commit()

    with given(_setup(agents_named("Oldest", "Newest"), newest_has_slack_and_memory)) as context:
        with when("Cloud Tier 1 holds the newest Agent, then the Organization moves to Free"):
            put_on(context, "cloud_1")
            assert_that(stored(context, "Newest").suspended_at, is_(not_none()))
            assert_that(stored(context, "Newest").memory_enabled, is_(True))
            put_on(context, "free")

        with then("the held Agent's Slack and memory are held too, so releasing it brings neither back"):
            (slack,) = connections_of(context)
            assert_that((slack.enabled, slack.suspension_reason), equal_to((False, SuspensionReason.TIER)))
            newest = stored(context, "Newest")
            assert_that(
                (newest.memory_enabled, newest.memory_suspension_reason), equal_to((False, SuspensionReason.TIER))
            )


def test_taking_an_organization_off_any_tier_holds_nothing():
    with given(_setup(agents_named("Oldest", "Newest"))) as context:
        a_platform_administrator_is_signed_in(context)

        response = assign(context, None)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(stored(context, "Newest").suspended_at, is_(none()))
        assert_that(events_named(context, "organization.tier_holds.changed"), equal_to([]))


def test_editing_a_tier_down_holds_in_every_organization_on_it():
    with given(_setup(agents_named("Oldest", "Newest"))) as context:
        put_on(context, "cloud_2")
        assert_that(stored(context, "Newest").suspended_at, is_(none()))

        with when("a Platform Administrator lowers Cloud Tier 2 to one agent"):
            response = context.client.patch(
                f"/api/v1/platform/tiers/{TIER_IDS['cloud_2']}",
                json={"agent_limit": 1},
                headers=auth(context.access_token),
            )

        with then("the newest Agent is held"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(stored(context, "Newest").suspended_at, is_(not_none()))


def test_lowering_the_trial_agent_limit_holds_like_any_free_tier_change():
    def trial_limit(context, limit: int):
        return context.client.put(
            "/api/v1/platform/settings/trial", json={"agent_limit": limit}, headers=auth(context.access_token)
        )

    with given(_setup(agents_named("Oldest", "Newest"))) as context:
        a_platform_administrator_is_signed_in(context)
        trial_limit(context, 2)
        put_on(context, "free")
        assert_that(stored(context, "Newest").suspended_at, is_(none()))

        with when("a Platform Administrator lowers the trial's agent limit to one in Signup & trials"):
            response = trial_limit(context, 1)

        with then("the newest Agent is held, and the change is audited as the Free Tier's"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(stored(context, "Newest").suspended_at, is_(not_none()))
            assert_that(
                [event.payload for event in events_named(context, "platform.tier.changed")],
                has_item(has_entries(setting="agent_limit", previous=2, current=1)),
            )


# --- choosing what to keep ---------------------------------------------------------------


def test_an_owner_swaps_which_agent_is_held():
    with given(_setup(agents_named("Oldest", "Newest"))) as context:
        put_on(context, "free")
        oldest, newest = context.agents["Oldest"].id, context.agents["Newest"].id

        with when("the owner releases the held Agent before holding the kept one, then in order"):
            refused = context.client.post(holds_url(context, f"/agents/{newest}/release"), headers=as_owner(context))
            held = context.client.post(holds_url(context, f"/agents/{oldest}/hold"), headers=as_owner(context))
            released = context.client.post(holds_url(context, f"/agents/{newest}/release"), headers=as_owner(context))

        with then("releasing waits for a place; once one is freed, the two swap"):
            assert_that(refused.status_code, equal_to(status.HTTP_409_CONFLICT), refused.text)
            assert_that(held.status_code, equal_to(status.HTTP_200_OK), held.text)
            assert_that(released.status_code, equal_to(status.HTTP_200_OK), released.text)
            assert_that(stored(context, "Oldest").suspended_at, is_(not_none()))
            assert_that(stored(context, "Newest").suspended_at, is_(none()))
            reasons = [event.payload["reason"] for event in events_named(context, "organization.tier_holds.changed")]
            assert_that(reasons, equal_to(["tier", "choice", "choice"]))


def test_an_upgrade_releases_nothing_until_the_owner_re_enables_it():
    with given(_setup(agents_named("Oldest", "Newest"))) as context:
        _create_webhook(context)
        put_on(context, "free")
        put_on(context, "cloud_2")
        (webhook,) = webhooks_of(context)
        assert_that((webhook.enabled, stored(context, "Newest").suspended_at is not None), equal_to((False, True)))

        with when("the owner enables the webhook again and releases the held Agent"):
            enabled = context.client.patch(
                agent_url(context, f"/webhooks/{webhook.id}"),
                json={"enabled": True, "revision": webhook.revision},
                headers=as_owner(context),
            )
            released = context.client.post(
                holds_url(context, f"/agents/{context.agents['Newest'].id}/release"), headers=as_owner(context)
            )

        with then("both are back, and the Agent stays stopped until started"):
            assert_that(enabled.status_code, equal_to(status.HTTP_200_OK), enabled.text)
            assert_that(enabled.json(), has_entries(enabled=True, suspended_at=None))
            assert_that(released.status_code, equal_to(status.HTTP_200_OK), released.text)
            assert_that(stored(context, "Newest"), has_properties_of(suspended_at=None, status=AgentStatus.STOPPED))


def test_a_member_cannot_choose_what_the_organization_keeps():
    def a_member_with_agent_access_is_signed_in(context):
        there_is_a_user(email="member@example.com", role=OrganizationRole.MEMBER)(context)
        there_is_an_access_token_for_user()(context)

    with given(_setup(agents_named("Oldest", "Newest"))) as context:
        put_on(context, "free")
        a_member_with_agent_access_is_signed_in(context)
        member = auth(context.access_token)

        listed = context.client.get(holds_url(context), headers=member)
        hidden = context.client.post(holds_url(context, f"/agents/{context.agents['Oldest'].id}/hold"), headers=member)

        assert_that(listed.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        # A Member without access to the Agent can't learn it exists.
        assert_that(hidden.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_the_agent_read_says_it_is_held():
    with given(_setup(agents_named("Oldest", "Newest"))) as context:
        put_on(context, "free")
        context.agent = context.agents["Newest"]

        response = context.client.get(agent_url(context), headers=as_owner(context))

        assert_that(response.json(), has_entries(suspended_at=not_none(), suspension_reason="tier"))


def test_holds_apply_once():
    with given(_setup(agents_named("Oldest", "Newest"))) as context:
        put_on(context, "free")
        context.injector.get(TierRepository).update_with_events(
            TIER_IDS["free"], {"tagline": "Changed"}, actor=Actor(user_id=context.user.id, display="Admin")
        )

        assert_that(events_named(context, "organization.tier_holds.changed"), has_length(1))
