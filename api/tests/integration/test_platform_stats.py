"""Integration tests for the Platform View stats surface (AF-256).

These endpoints are cross-Organization by design: a Platform Administrator reads
them without an Active Organization, so the assertions here deliberately seed
more than one Organization and expect both to be counted.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from fastapi import status
from hamcrest import assert_that, equal_to, greater_than, has_key, has_length, not_
from sqlmodel import col, select

from api.domains.agents.models import Agent, AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.models import (
    CommunicationConnection,
    CommunicationPlatform,
    CommunicationSender,
    ConversationLocation,
    NormalizedCommunicationEnvelope,
    RuntimeReplyCreate,
)
from api.domains.communications.repository import CommunicationConnectionRepository
from api.domains.conversations.models import AgentChatMessage
from api.domains.events.models import ActorIdentity, ActorIdentityType
from api.domains.tool_calls.models import ToolCall, ToolCallStatus
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization,
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_MESSAGES_URL = "/api/v1/platform/stats/messages"
_AGENTS_URL = "/api/v1/platform/stats/agents"

_ENV = set_env_variable(
    {
        "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
        "LITELLM_BASE_URL": "http://litellm:4000",
        "LITELLM_SECRET_NAME": "litellm",
        "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
        "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
    }
)

_BASE_GIVEN = [
    _ENV,
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
]


def _day_of(point: dict) -> str:
    """UTC date of a series bucket — buckets are instants now, not dates."""
    return point["bucket"][:10]


def _by_day(body: dict) -> dict:
    return {_day_of(p): p for p in body["series"]}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _seed_connection(context, *, agent, platform=CommunicationPlatform.SLACK, display_name=None):
    """One Communication Connection for an Agent."""
    delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
    connection = CommunicationConnection(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        platform_key=platform.value,
        display_name=display_name or f"Stats {platform.value} {uuid7()}",
        credentials_encrypted="test-credentials",
        driver_key_encrypted="test-driver-key",
    )
    delegate.save(connection)
    return connection


def _accept_inbound(context, *, connection, occurred_at, suffix=""):
    """Admit one provider message through the Communications Gateway."""
    repository: CommunicationDeliveryRepository = context.injector.get(CommunicationDeliveryRepository)
    envelope = NormalizedCommunicationEnvelope(
        provider_message_id=f"in-{occurred_at.isoformat()}-{suffix}",
        occurred_at=occurred_at,
        location=ConversationLocation(id="CHANNEL:C1", type="CHANNEL", display_name="general"),
        sender=CommunicationSender(id="U1", display_name="Sender"),
        text="hello",
    )
    return repository.accept_inbound(connection_id=connection.id, envelope=envelope)


def _seed_reply(context, *, agent, delivery_id, occurred_at, suffix=""):
    """Answer one inbound delivery through the gateway, backdating the row it wrote."""
    repository: CommunicationDeliveryRepository = context.injector.get(CommunicationDeliveryRepository)
    idempotency_key = f"out-{occurred_at.isoformat()}-{suffix}"
    repository.enqueue_runtime_reply(
        agent_id=agent.id,
        source_delivery_id=delivery_id,
        reply=RuntimeReplyCreate(idempotency_key=idempotency_key, text="ack"),
    )
    delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
    message = delegate.find_one_by_query(
        AgentChatMessage,
        select(AgentChatMessage).where(col(AgentChatMessage.openclaw_msg_id) == f"outbound:{idempotency_key}"),
    )
    assert message is not None
    message.occurred_at = occurred_at
    delegate.save(message)


def _seed_message(
    context,
    *,
    agent_id,
    occurred_at,
    suffix="",
    platform=CommunicationPlatform.SLACK,
):
    """One received message on a Connection of its own, through the gateway."""
    delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
    agent = delegate.find_by_id(Agent, agent_id)
    assert agent is not None
    connection = _seed_connection(context, agent=agent, platform=platform)
    return _accept_inbound(context, connection=connection, occurred_at=occurred_at, suffix=suffix)


def _soft_delete_agent(context, agent):
    """Delete an Agent the way the product does, retiring its Connections."""
    repository: AgentRepository = context.injector.get(AgentRepository)
    repository.soft_delete_with_event(
        agent,
        actor=ActorIdentity(type=ActorIdentityType.USER, id=uuid7()),
    )


def _seed_tool_call(context, *, agent, occurred_at, suffix=""):
    """Insert one completed tool call directly, the way ingest would."""
    delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
    delegate.save(
        ToolCall(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            session_id="session-1",
            external_id=f"tc-{occurred_at.isoformat()}-{suffix}",
            tool_name="search",
            arguments={},
            status=ToolCallStatus.SUCCESS,
            occurred_at=occurred_at,
        )
    )


def _platform_admin(email: str):
    """A Platform Administrator whose token lands last in context.access_token.

    `there_is_a_user` attaches the new user to `context.organization` as OWNER
    when one is present, which both collides with the existing owner and would
    give this user exactly the Membership these endpoints must not need. Hiding
    the Organization for the duration keeps the admin membership-free, which is
    the whole point of Platform View.
    """
    admin_id = uuid7()

    def step(context):
        original_organization = getattr(context, "organization", None)
        context.organization = None
        there_is_a_user(id=admin_id, email=email, is_platform_admin=True)(context)
        context.organization = original_organization
        there_is_an_access_token_for_user(user_id=admin_id)(context)

    return [step]


# --- authorization -------------------------------------------------------


def test_message_stats_rejects_a_regular_user():
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="plain@example.com"),
        ]
    ) as context:
        with when("a user without Platform Privilege asks for message stats"):
            response = context.client.get(_MESSAGES_URL, headers=_auth(context.access_token))

        with then("the platform surface is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_agent_stats_rejects_a_regular_user():
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="plain2@example.com"),
        ]
    ) as context:
        with when("a user without Platform Privilege asks for agent stats"):
            response = context.client.get(_AGENTS_URL, headers=_auth(context.access_token))

        with then("the platform surface is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_message_stats_requires_authentication():
    with given(_BASE_GIVEN) as context:
        response = context.client.get(_MESSAGES_URL)
        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


# --- message stats -------------------------------------------------------


def test_message_stats_splits_inbound_and_outbound_within_the_window():
    now = datetime.now(UTC)
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-a@example.com"),
            there_is_an_agent(name="Agent A"),
            *_platform_admin("admin-split@example.com"),
        ]
    ) as context:
        agent_id = context.agent.id
        received = [
            _seed_message(
                context,
                agent_id=agent_id,
                occurred_at=now - timedelta(days=1, minutes=index),
                suffix=str(index),
            )
            for index in range(3)
        ]
        _seed_reply(
            context,
            agent=context.agent,
            delivery_id=received[0].delivery_id,
            occurred_at=now - timedelta(days=1),
        )

        with when("a Platform Administrator reads the default period"):
            response = context.client.get(_MESSAGES_URL, headers=_auth(context.access_token))

        with then("inbound and outbound are counted separately and totalled"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["inbound"], equal_to(3))
            assert_that(body["outbound"], equal_to(1))
            assert_that(body["total"], equal_to(4))
            assert_that(body["period"], equal_to("THIRTY_DAYS"))


def test_message_stats_excludes_messages_outside_the_period():
    now = datetime.now(UTC)
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-b@example.com"),
            there_is_an_agent(name="Agent B"),
            *_platform_admin("admin-window@example.com"),
        ]
    ) as context:
        agent_id = context.agent.id
        _seed_message(
            context,
            agent_id=agent_id,
            occurred_at=now - timedelta(days=2),
            suffix="recent",
        )
        _seed_message(
            context,
            agent_id=agent_id,
            occurred_at=now - timedelta(days=40),
            suffix="old",
        )

        with when("the seven-day period is requested"):
            response = context.client.get(
                _MESSAGES_URL,
                params={"period": "SEVEN_DAYS"},
                headers=_auth(context.access_token),
            )

        with then("only the message inside the window is counted"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["inbound"], equal_to(1))
            assert_that(body["period"], equal_to("SEVEN_DAYS"))

        with when("the ninety-day period is requested"):
            wide = context.client.get(
                _MESSAGES_URL,
                params={"period": "NINETY_DAYS"},
                headers=_auth(context.access_token),
            )

        with then("both messages are counted"):
            assert_that(wide.json()["inbound"], equal_to(2))


def test_message_stats_buckets_the_series_by_utc_day():
    now = datetime.now(UTC)
    day_one = (now - timedelta(days=3)).replace(hour=23, minute=30, second=0, microsecond=0)
    day_two = day_one + timedelta(hours=1)  # crosses midnight UTC

    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-c@example.com"),
            there_is_an_agent(name="Agent C"),
            *_platform_admin("admin-buckets@example.com"),
        ]
    ) as context:
        agent_id = context.agent.id
        received = _seed_message(context, agent_id=agent_id, occurred_at=day_one)
        _seed_reply(context, agent=context.agent, delivery_id=received.delivery_id, occurred_at=day_two)

        with when("the series is read"):
            response = context.client.get(_MESSAGES_URL, headers=_auth(context.access_token))

        with then("the two sides of UTC midnight land in different buckets"):
            body = response.json()
            # The series is gap-filled, so index by day rather than position.
            by_date = _by_day(body)
            assert_that(by_date[day_one.date().isoformat()]["inbound"], equal_to(1))
            assert_that(by_date[day_one.date().isoformat()]["outbound"], equal_to(0))
            assert_that(by_date[day_two.date().isoformat()]["outbound"], equal_to(1))
            assert_that(by_date[day_two.date().isoformat()]["inbound"], equal_to(0))


def test_message_stats_counts_messages_of_soft_deleted_agents():
    now = datetime.now(UTC)
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-d@example.com"),
            there_is_an_agent(name="Retired Agent"),
            *_platform_admin("admin-deleted@example.com"),
        ]
    ) as context:
        _seed_message(
            context,
            agent_id=context.agent.id,
            occurred_at=now - timedelta(days=1),
        )
        _soft_delete_agent(context, context.agent)

        with when("the stats are read"):
            response = context.client.get(_MESSAGES_URL, headers=_auth(context.access_token))

        with then("historical volume survives the Agent's retirement"):
            assert_that(response.json()["inbound"], equal_to(1))


def test_message_stats_spans_organizations():
    now = datetime.now(UTC)
    other_org_id = uuid7()
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-e@example.com"),
            there_is_an_agent(name="Agent Home"),
            *_platform_admin("admin-cross-org@example.com"),
        ]
    ) as context:
        _seed_message(
            context,
            agent_id=context.agent.id,
            occurred_at=now - timedelta(days=1),
            suffix="home",
        )

        from api.tests.steps.organization import there_is_an_organization

        home_org = context.organization
        there_is_an_organization(id=other_org_id, name="Other Org")(context)
        there_is_an_agent(name="Agent Other", organization_id=other_org_id)(context)
        context.organization = home_org

        _seed_message(
            context,
            agent_id=context.agent.id,
            occurred_at=now - timedelta(days=1),
            suffix="other",
        )

        with when("a Platform Administrator reads the stats"):
            response = context.client.get(_MESSAGES_URL, headers=_auth(context.access_token))

        with then("both Organizations are counted"):
            assert_that(response.json()["inbound"], equal_to(2))


def test_message_stats_rejects_an_unknown_period():
    with given(
        [
            *_BASE_GIVEN,
            *_platform_admin("admin-bad-period@example.com"),
        ]
    ) as context:
        response = context.client.get(
            _MESSAGES_URL,
            params={"period": "FOREVER"},
            headers=_auth(context.access_token),
        )
        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_message_stats_excludes_message_content_and_identity():
    now = datetime.now(UTC)
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-f@example.com"),
            there_is_an_agent(name="Agent F"),
            *_platform_admin("admin-allowlist@example.com"),
        ]
    ) as context:
        _seed_message(
            context,
            agent_id=context.agent.id,
            occurred_at=now - timedelta(days=1),
        )

        response = context.client.get(_MESSAGES_URL, headers=_auth(context.access_token))

        with then("no tenant content leaks into the Platform Oversight projection"):
            body = response.json()
            for forbidden in ("content", "sender_id", "sender_name", "channel_id", "session_key"):
                assert_that(body, not_(has_key(forbidden)))
            for point in body["series"]:
                assert_that(point, not_(has_key("content")))


# --- agent stats ---------------------------------------------------------


def test_agent_stats_counts_all_and_running_separately():
    other_org_id = uuid7()
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-g@example.com"),
            there_is_an_agent(name="Running One", status=AgentStatus.RUNNING),
            there_is_an_agent(name="Stopped One", status=AgentStatus.STOPPED),
            there_is_an_agent(name="Gone One", deleted=True),
            *_platform_admin("admin-agents@example.com"),
        ]
    ) as context:
        from api.tests.steps.organization import there_is_an_organization

        home_org = context.organization
        there_is_an_organization(id=other_org_id, name="Other Agent Org")(context)
        there_is_an_agent(
            name="Running Elsewhere",
            status=AgentStatus.RUNNING,
            organization_id=other_org_id,
        )(context)
        context.organization = home_org

        with when("a Platform Administrator reads agent stats"):
            response = context.client.get(_AGENTS_URL, headers=_auth(context.access_token))

        with then("soft-deleted Agents are excluded and running is a separate number"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["total"], equal_to(3))
            assert_that(body["running"], equal_to(2))
            assert_that(body["stopped"], equal_to(1))
            assert_that(body["errored"], equal_to(0))
            # The status counts partition the live total.
            assert_that(body["running"] + body["stopped"] + body["errored"], equal_to(body["total"]))


def test_agent_stats_series_tracks_inventory_over_time():
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-h@example.com"),
            there_is_an_agent(name="Series Agent", status=AgentStatus.RUNNING),
            *_platform_admin("admin-agent-series@example.com"),
        ]
    ) as context:
        with when("the agent series is read"):
            response = context.client.get(_AGENTS_URL, headers=_auth(context.access_token))

        with then("every day in the window is present and today carries the Agent"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            # 30-day window inclusive of both ends
            assert_that(body["series"], has_length(31))
            assert_that(body["series"][-1]["existing"], equal_to(1))
            assert_that(body["series"][-1]["created"], equal_to(1))
            # The Agent did not exist a month ago.
            assert_that(body["series"][0]["existing"], equal_to(0))
            assert_that(body["period"], equal_to("THIRTY_DAYS"))


def test_agent_activity_counts_messages_and_tool_calls_without_double_counting():
    now = datetime.now(UTC)
    yesterday = (now - timedelta(days=1)).date().isoformat()

    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-n@example.com"),
            there_is_an_agent(name="Chatty Agent"),
            *_platform_admin("admin-activity@example.com"),
        ]
    ) as context:
        chatty = context.agent
        _seed_message(
            context,
            agent_id=chatty.id,
            occurred_at=now - timedelta(days=1),
        )
        # Same Agent, same day, both streams — must still be one active Agent.
        _seed_tool_call(context, agent=chatty, occurred_at=now - timedelta(days=1), suffix="chatty")

        there_is_an_agent(name="Silent Agent")(context)

        with when("the agent stats are read"):
            response = context.client.get(_AGENTS_URL, headers=_auth(context.access_token))

        with then("only the Agent with telemetry is active, counted once"):
            body = response.json()
            by_date = _by_day(body)
            assert_that(by_date[yesterday]["active"], equal_to(1))
            assert_that(body["active"], equal_to(1))
            # Inventory follows created_at, so both Agents only exist from today;
            # activity follows the telemetry's occurred_at, which is backdated.
            assert_that(body["series"][-1]["existing"], equal_to(2))


def test_an_agent_active_only_through_tool_calls_is_counted():
    """A scheduled run leaves no message behind — the runtime plugins drop
    outbound messages on non-user-triggered turns — so tool calls are the only
    evidence that proactive work happened."""
    now = datetime.now(UTC)
    yesterday = (now - timedelta(days=1)).date().isoformat()

    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-o@example.com"),
            there_is_an_agent(name="Cron Agent"),
            *_platform_admin("admin-cron-activity@example.com"),
        ]
    ) as context:
        _seed_tool_call(context, agent=context.agent, occurred_at=now - timedelta(days=1), suffix="cron")

        with when("the agent stats are read"):
            response = context.client.get(_AGENTS_URL, headers=_auth(context.access_token))

        with then("tool-only activity still registers"):
            body = response.json()
            by_date = _by_day(body)
            assert_that(by_date[yesterday]["active"], equal_to(1))
            assert_that(body["active"], equal_to(1))


def test_agents_with_no_telemetry_are_never_active():
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-p@example.com"),
            there_is_an_agent(name="Idle Agent", status=AgentStatus.RUNNING),
            *_platform_admin("admin-idle@example.com"),
        ]
    ) as context:
        response = context.client.get(_AGENTS_URL, headers=_auth(context.access_token))

        with then("being up is not the same as doing work"):
            body = response.json()
            assert_that(body["running"], equal_to(1))
            assert_that(body["active"], equal_to(0))
            assert_that({point["active"] for point in body["series"]}, equal_to({0}))


def test_series_buckets_carry_a_utc_offset():
    """A bucket without an offset is parsed as local time by browsers, which
    shifts every chart label by the viewer's timezone."""
    now = datetime.now(UTC)
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-tz@example.com"),
            there_is_an_agent(name="TZ Agent"),
            *_platform_admin("admin-tz@example.com"),
        ]
    ) as context:
        _seed_message(
            context,
            agent_id=context.agent.id,
            occurred_at=now - timedelta(days=1),
        )

        for url in (_MESSAGES_URL, _AGENTS_URL):
            body = context.client.get(url, headers=_auth(context.access_token)).json()
            for point in body["series"][:3]:
                bucket = point["bucket"]
                assert_that(
                    bucket.endswith("Z") or "+" in bucket[10:],
                    equal_to(True),
                )


def test_an_oversized_bucket_request_is_rejected():
    with given([*_BASE_GIVEN, *_platform_admin("admin-buckets-cap@example.com")]) as context:
        response = context.client.get(
            _MESSAGES_URL,
            params={
                "from_date": "1970-01-01T00:00:00Z",
                "to_date": "2030-01-01T00:00:00Z",
                "granularity": "minute",
            },
            headers=_auth(context.access_token),
        )
        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


# --- filters -------------------------------------------------------------


def test_stats_filter_by_organization():
    now = datetime.now(UTC)
    other_org_id = uuid7()
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-i@example.com"),
            there_is_an_agent(name="Home Agent"),
            *_platform_admin("admin-org-filter@example.com"),
        ]
    ) as context:
        from api.tests.steps.organization import there_is_an_organization

        home_org_id = context.organization.id
        _seed_message(
            context,
            agent_id=context.agent.id,
            occurred_at=now - timedelta(days=1),
            suffix="home",
        )

        home_org = context.organization
        there_is_an_organization(id=other_org_id, name="Filter Other Org")(context)
        there_is_an_agent(name="Other Agent", organization_id=other_org_id)(context)
        context.organization = home_org
        _seed_message(
            context,
            agent_id=context.agent.id,
            occurred_at=now - timedelta(days=1),
            suffix="other",
        )

        with when("messages are narrowed to one Organization"):
            response = context.client.get(
                _MESSAGES_URL,
                params={"organization_id": str(home_org_id)},
                headers=_auth(context.access_token),
            )

        with then("only that Organization's volume is counted"):
            assert_that(response.json()["inbound"], equal_to(1))

        with when("agents are narrowed to the same Organization"):
            agents = context.client.get(
                _AGENTS_URL,
                params={"organization_id": str(other_org_id)},
                headers=_auth(context.access_token),
            )

        with then("only that Organization's Agents are counted"):
            assert_that(agents.json()["total"], equal_to(1))


def test_stats_filter_by_agent_and_platform():
    now = datetime.now(UTC)
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-j@example.com"),
            there_is_an_agent(name="Slack Agent"),
            *_platform_admin("admin-agent-filter@example.com"),
        ]
    ) as context:
        slack_agent_id = context.agent.id
        _seed_message(
            context,
            agent_id=slack_agent_id,
            occurred_at=now - timedelta(days=1),
            suffix="slack",
        )
        there_is_an_agent(name="Telegram Agent")(context)
        _seed_message(
            context,
            agent_id=context.agent.id,
            occurred_at=now - timedelta(days=1),
            suffix="telegram",
            platform=CommunicationPlatform.TELEGRAM,
        )

        with when("messages are narrowed to one Agent"):
            by_agent = context.client.get(
                _MESSAGES_URL,
                params={"agent_id": str(slack_agent_id)},
                headers=_auth(context.access_token),
            )

        with then("the other Agent's volume is excluded"):
            assert_that(by_agent.json()["inbound"], equal_to(1))

        with when("messages are narrowed to one chat platform"):
            by_platform = context.client.get(
                _MESSAGES_URL,
                params={"platform": "telegram"},
                headers=_auth(context.access_token),
            )

        with then("only that platform's volume is counted"):
            assert_that(by_platform.json()["inbound"], equal_to(1))

        with when("agents are narrowed to one chat platform"):
            agents = context.client.get(
                _AGENTS_URL,
                params={"platform": "slack"},
                headers=_auth(context.access_token),
            )

        with then("only that platform's Agents are counted"):
            assert_that(agents.json()["total"], equal_to(1))


def test_stats_reject_an_unknown_platform_filter():
    with given(
        [
            *_BASE_GIVEN,
            *_platform_admin("admin-bad-platform@example.com"),
        ]
    ) as context:
        response = context.client.get(
            _MESSAGES_URL,
            params={"platform": "carrier-pigeon"},
            headers=_auth(context.access_token),
        )
        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_agent_stats_reports_zero_on_an_empty_platform():
    with given(
        [
            *_BASE_GIVEN,
            *_platform_admin("admin-empty@example.com"),
        ]
    ) as context:
        response = context.client.get(_AGENTS_URL, headers=_auth(context.access_token))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["total"], equal_to(0))
        assert_that(body["running"], equal_to(0))
        assert_that(len(body["observed_at"]), greater_than(0))


# --- metric contract -----------------------------------------------------


@dataclass
class _ContractFixture:
    home_org_id: UUID
    other_org_id: UUID
    multi_agent_id: UUID
    tool_only_agent_id: UUID


def _seed_contract_fixture(context, now) -> _ContractFixture:
    """Every lifecycle and filter edge the aggregates have to agree on."""
    inside = now - timedelta(days=1)
    home_org_id = context.organization.id
    other_org_id = uuid7()

    there_is_an_agent(name="Multi Platform")(context)
    multi = context.agent
    slack_connection = _seed_connection(context, agent=multi, display_name="Multi Slack")
    telegram_connection = _seed_connection(
        context, agent=multi, platform=CommunicationPlatform.TELEGRAM, display_name="Multi Telegram"
    )
    accepted = _accept_inbound(context, connection=slack_connection, occurred_at=inside, suffix="multi-slack")
    _accept_inbound(context, connection=telegram_connection, occurred_at=inside, suffix="multi-telegram")
    _seed_reply(context, agent=multi, delivery_id=accepted.delivery_id, occurred_at=inside, suffix="multi")

    there_is_an_agent(name="Steady")(context)
    steady_connection = _seed_connection(context, agent=context.agent, display_name="Steady Slack")
    _accept_inbound(context, connection=steady_connection, occurred_at=inside, suffix="steady")
    _accept_inbound(context, connection=steady_connection, occurred_at=now - timedelta(days=40), suffix="before")
    _accept_inbound(context, connection=steady_connection, occurred_at=now + timedelta(days=1), suffix="after")

    there_is_an_agent(name="Departed")(context)
    departed = context.agent
    departed_connection = _seed_connection(context, agent=departed, display_name="Departed Slack")
    _accept_inbound(context, connection=departed_connection, occurred_at=inside, suffix="departed")
    _soft_delete_agent(context, departed)

    there_is_an_agent(name="Reconnected")(context)
    reconnected = context.agent
    retired_connection = _seed_connection(context, agent=reconnected, display_name="Reconnected Slack")
    _accept_inbound(context, connection=retired_connection, occurred_at=inside, suffix="reconnected")
    connections: CommunicationConnectionRepository = context.injector.get(CommunicationConnectionRepository)
    connections.retire(retired_connection.id, expected_revision=retired_connection.revision)

    there_is_an_agent(name="Scheduled")(context)
    tool_only = context.agent
    _seed_tool_call(context, agent=tool_only, occurred_at=inside, suffix="scheduled")

    there_is_an_agent(name="Nightly")(context)
    nightly = context.agent
    _seed_connection(context, agent=nightly, display_name="Nightly Slack")
    _seed_tool_call(context, agent=nightly, occurred_at=inside, suffix="nightly")
    _soft_delete_agent(context, nightly)

    home_org = context.organization
    there_is_an_organization(id=other_org_id, name="Contract Other Org")(context)
    there_is_an_agent(name="Teams Agent", organization_id=other_org_id)(context)
    teams_agent = context.agent
    context.organization = home_org
    teams_connection = _seed_connection(
        context, agent=teams_agent, platform=CommunicationPlatform.TEAMS, display_name="Teams"
    )
    _accept_inbound(context, connection=teams_connection, occurred_at=inside, suffix="teams")

    return _ContractFixture(
        home_org_id=home_org_id,
        other_org_id=other_org_id,
        multi_agent_id=multi.id,
        tool_only_agent_id=tool_only.id,
    )


_CONTRACT_GIVEN = [
    *_BASE_GIVEN,
    there_is_an_organization_with_user_and_access_token(email="owner-contract@example.com"),
    *_platform_admin("admin-contract@example.com"),
]


def _messages(context, **params):
    return context.client.get(_MESSAGES_URL, params=params, headers=_auth(context.access_token)).json()


def _agents(context, **params):
    return context.client.get(_AGENTS_URL, params=params, headers=_auth(context.access_token)).json()


def test_contract_unfiltered_counts_every_message_in_the_window():
    now = datetime.now(UTC)
    with given(_CONTRACT_GIVEN) as context:
        _seed_contract_fixture(context, now)

        with when("the whole platform is read"):
            body = _messages(context)

        with then("every in-window message counts once, and the edges are excluded"):
            assert_that(body["inbound"], equal_to(6))
            assert_that(body["outbound"], equal_to(1))
            assert_that(body["total"], equal_to(7))


def test_contract_unfiltered_agent_counts_split_live_from_historical():
    now = datetime.now(UTC)
    with given(_CONTRACT_GIVEN) as context:
        _seed_contract_fixture(context, now)

        with when("the whole platform is read"):
            body = _agents(context)

        with then("the status split covers the live Agents only"):
            assert_that(body["total"], equal_to(5))
            assert_that(body["running"] + body["stopped"] + body["errored"], equal_to(body["total"]))

        with then("activity is historical and includes the deleted Agents"):
            assert_that(body["active"], equal_to(7))


def test_contract_messaging_app_filter_follows_the_message_not_the_agent():
    now = datetime.now(UTC)
    with given(_CONTRACT_GIVEN) as context:
        _seed_contract_fixture(context, now)

        with when("messages are narrowed to one messaging app"):
            slack = _messages(context, platform="slack")
            telegram = _messages(context, platform="telegram")

        with then("a two-platform Agent's traffic is split, not double counted"):
            assert_that(slack["inbound"], equal_to(4))
            assert_that(slack["outbound"], equal_to(1))
            assert_that(telegram["inbound"], equal_to(1))
            assert_that(telegram["outbound"], equal_to(0))


def test_contract_teams_traffic_can_be_isolated():
    now = datetime.now(UTC)
    with given(_CONTRACT_GIVEN) as context:
        _seed_contract_fixture(context, now)

        with when("messages are narrowed to Teams"):
            body = _messages(context, platform="teams")

        with then("the Teams Connection's volume is reported on its own"):
            assert_that(body["inbound"], equal_to(1))


def test_contract_filtered_activity_survives_deletion_and_retirement():
    now = datetime.now(UTC)
    with given(_CONTRACT_GIVEN) as context:
        _seed_contract_fixture(context, now)

        with when("agents are narrowed to one messaging app"):
            body = _agents(context, platform="slack")

        with then("history keeps the deleted Agents and the retired Connection"):
            assert_that(body["active"], equal_to(5))

        with then("the inventory series counts every Agent that was on it"):
            assert_that(sum(point["created"] for point in body["series"]), equal_to(5))
            assert_that(body["series"][-1]["existing"], equal_to(3))

        with then("the point-in-time split keeps only Agents live on it now"):
            assert_that(body["total"], equal_to(2))


def test_contract_series_sums_to_its_tiles():
    now = datetime.now(UTC)
    with given(_CONTRACT_GIVEN) as context:
        _seed_contract_fixture(context, now)

        with when("both surfaces are read unfiltered"):
            messages = _messages(context)
            agents = _agents(context)

        with then("the message series accounts for every counted message"):
            assert_that(sum(p["inbound"] for p in messages["series"]), equal_to(messages["inbound"]))
            assert_that(sum(p["outbound"] for p in messages["series"]), equal_to(messages["outbound"]))

        with then("no bucket claims more active Agents than the period total"):
            assert_that(max(p["active"] for p in agents["series"]), equal_to(agents["active"]))


def test_contract_organization_filter_narrows_both_surfaces():
    now = datetime.now(UTC)
    with given(_CONTRACT_GIVEN) as context:
        fixture = _seed_contract_fixture(context, now)

        with when("both surfaces are narrowed to the second Organization"):
            messages = _messages(context, organization_id=str(fixture.other_org_id))
            agents = _agents(context, organization_id=str(fixture.other_org_id))

        with then("only that Organization's Teams Agent is represented"):
            assert_that(messages["inbound"], equal_to(1))
            assert_that(agents["total"], equal_to(1))
            assert_that(agents["active"], equal_to(1))


def test_contract_agent_filter_isolates_one_agent():
    now = datetime.now(UTC)
    with given(_CONTRACT_GIVEN) as context:
        fixture = _seed_contract_fixture(context, now)

        with when("both surfaces are narrowed to the two-platform Agent"):
            messages = _messages(context, agent_id=str(fixture.multi_agent_id))
            agents = _agents(context, agent_id=str(fixture.multi_agent_id))

        with then("both of its Connections are counted and nothing else is"):
            assert_that(messages["inbound"], equal_to(2))
            assert_that(messages["outbound"], equal_to(1))
            assert_that(agents["total"], equal_to(1))
            assert_that(agents["active"], equal_to(1))


def test_contract_tool_only_agent_is_active_without_messages():
    now = datetime.now(UTC)
    with given(_CONTRACT_GIVEN) as context:
        fixture = _seed_contract_fixture(context, now)

        with when("the surfaces are narrowed to an Agent that only ran tools"):
            messages = _messages(context, agent_id=str(fixture.tool_only_agent_id))
            agents = _agents(context, agent_id=str(fixture.tool_only_agent_id))

        with then("it counts as active with no message volume at all"):
            assert_that(messages["total"], equal_to(0))
            assert_that(agents["active"], equal_to(1))
