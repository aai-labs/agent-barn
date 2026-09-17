from datetime import UTC, datetime, timedelta

from fastapi import status
from hamcrest import assert_that, equal_to
from sqlmodel import Session, col, select
from starlette.testclient import TestClient

from api.domains.agents.repository import AgentRepository
from api.domains.communications.models import (
    CommunicationConnection,
    CommunicationJournalEntry,
    ConnectionObservedStatus,
)
from api.domains.conversations.models import AgentChatMessage, MessageDirection
from api.domains.rbac.policy import AuthorizationScope
from api.domains.tool_calls.repository import ToolCallRepository
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.ingest_app import create_ingest_app
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
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
    there_is_an_organization_with_user_and_access_token,
)

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
]


def _create_ingest_client():
    def step(context):
        app = create_ingest_app(injector=context.injector)
        context.ingest_client = TestClient(app)

    return step


def _set_ingest_key(key="test-ingest-key-abc"):
    def step(context):
        repo: AgentRepository = context.injector.get(AgentRepository)
        agent = repo.get_by_id(context.agent.id)
        assert agent is not None
        agent.ingest_key_encrypted = encrypt_token(key, TEST_ENCRYPTION_KEY)
        repo.save(agent)
        context.agent = agent
        context.ingest_key = key

    return step


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.ingest_key}"}


def _url(context) -> str:
    return f"/ingest/v1/agents/{context.agent.id}/events"


def _tool_call_payload(external_id="tc-1"):
    now = datetime.now(UTC).isoformat()
    return {
        "tool_calls": [
            {
                "external_id": external_id,
                "session_id": "session-abc",
                "tool_name": "read",
                "arguments": {"path": "/tmp/x"},
                "occurred_at": now,
            }
        ],
        "tool_results": [
            {
                "external_id": external_id,
                "result": "file contents",
                "is_error": False,
                "completed_at": now,
            }
        ],
    }


# --- auth ---


def test_ingest_no_auth_returns_422():
    with given([*_GIVEN, there_is_an_agent(), _set_ingest_key(), _create_ingest_client()]) as context:
        with when("I post without authorization header"):
            response = context.ingest_client.post(_url(context), json={"messages": []})

        with then("it returns 422"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_ingest_wrong_key_returns_401():
    with given([*_GIVEN, there_is_an_agent(), _set_ingest_key(), _create_ingest_client()]) as context:
        with when("I post with a wrong key"):
            response = context.ingest_client.post(
                _url(context),
                json={},
                headers={"Authorization": "Bearer wrong-key"},
            )

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


# --- tool calls ---


def test_ingest_tool_calls_returns_204_and_persists():
    with given([*_GIVEN, there_is_an_agent(), _set_ingest_key(), _create_ingest_client()]) as context:
        with when("I post a tool call + result"):
            response = context.ingest_client.post(
                _url(context),
                json=_tool_call_payload(),
                headers=_auth(context),
            )

        with then("it returns 204 and the tool call is in the DB"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            tc_repo: ToolCallRepository = context.injector.get(ToolCallRepository)
            from api.domains.tool_calls.models import ToolCallFilter
            from api.infrastructure.shared.models import Pagination

            page = tc_repo.find_by_agent(
                context.agent.id,
                ToolCallFilter(),
                Pagination(page=1, size=10),
                AuthorizationScope(organization_id=context.organization.id),
            )
            assert_that(page.total, equal_to(1))
            assert_that(page.items[0].tool_name, equal_to("read"))
            assert_that(page.items[0].status, equal_to("SUCCESS"))


# --- empty batch ---


def test_ingest_empty_batch_returns_204():
    with given([*_GIVEN, there_is_an_agent(), _set_ingest_key(), _create_ingest_client()]) as context:
        with when("I post an empty batch"):
            response = context.ingest_client.post(
                _url(context),
                json={},
                headers=_auth(context),
            )

        with then("it returns 204"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))


# --- native gateway communication events ---


def _native_slack_connection():
    def step(context):
        delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
        context.connection = CommunicationConnection(
            organization_id=context.agent.organization_id,
            agent_id=context.agent.id,
            platform_key="slack",
            display_name="Native Slack",
            credentials_encrypted="test-credentials",
            driver_key_encrypted="test-driver-key",
        )
        delegate.save(context.connection)

    return step


def _journal(context) -> list[CommunicationJournalEntry]:
    delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
    with Session(delegate.engine) as session:
        return list(
            session.exec(
                select(CommunicationJournalEntry)
                .where(col(CommunicationJournalEntry.agent_id) == context.agent.id)
                .order_by(col(CommunicationJournalEntry.occurred_at))
            ).all()
        )


def test_communication_events_append_one_delivery_timeline_per_inbound_message():
    with given(
        [*_GIVEN, there_is_an_agent(), _set_ingest_key(), _native_slack_connection(), _create_ingest_client()]
    ) as context:
        with when("the observer reports a message's stages, a health change, and an unmodelled stage"):
            base = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
            events = [
                ("provider_observed", "slack:1.1"),
                ("agent_claimed", "slack:1.1"),
                ("approval_requested", "slack:1.1"),
                ("provider_delivered", "slack:1.1"),
                ("provider_observed", "slack:2.2"),
                ("connection_degraded", None),
                ("provider_observed", "discord:3"),
            ]
            payload = {
                "events": [
                    {
                        "stage": stage,
                        "platform": (correlation or "slack").split(":")[0],
                        "correlation_id": correlation,
                        "occurred_at": (base + timedelta(seconds=i)).isoformat(),
                        "error_code": "ratelimited" if stage == "connection_degraded" else None,
                    }
                    for i, (stage, correlation) in enumerate(events)
                ]
            }
            response = context.ingest_client.post(
                f"/ingest/v1/agents/{context.agent.id}/communication-events", json=payload, headers=_auth(context)
            )

        with then("known stages on the matching Connection are journalled, grouped by inbound message"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            entries = _journal(context)
            assert_that(
                [entry.stage for entry in entries],
                equal_to(
                    [
                        "provider_observed",
                        "agent_claimed",
                        "provider_delivered",
                        "provider_observed",
                        "connection_degraded",
                    ]
                ),
            )
            assert_that({entry.connection_id for entry in entries}, equal_to({context.connection.id}))
            first, second = entries[0].delivery_id, entries[3].delivery_id
            assert_that([entry.delivery_id for entry in entries[:3]], equal_to([first, first, first]))
            assert_that(second is not None and second != first, equal_to(True))
            assert_that(entries[4].delivery_id, equal_to(None))
            assert_that(entries[4].error_code, equal_to("ratelimited"))
            delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
            with Session(delegate.engine) as session:
                connection = session.get(CommunicationConnection, context.connection.id)
                assert connection is not None
                assert_that(connection.observed_status, equal_to(ConnectionObservedStatus.DEGRADED))


def test_communication_events_reject_wrong_key():
    with given(
        [*_GIVEN, there_is_an_agent(), _set_ingest_key(), _native_slack_connection(), _create_ingest_client()]
    ) as context:
        with when("I post with the wrong key"):
            response = context.ingest_client.post(
                f"/ingest/v1/agents/{context.agent.id}/communication-events",
                json={"events": []},
                headers={"Authorization": "Bearer wrong"},
            )

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_communication_events_mirror_native_transcripts_to_dashboard_conversations():
    with given(
        [*_GIVEN, there_is_an_agent(), _set_ingest_key(), _native_slack_connection(), _create_ingest_client()]
    ) as context:
        observed_at = datetime(2026, 9, 17, 12, 0, tzinfo=UTC).isoformat()
        payload = {
            "events": [],
            "messages": [
                {
                    "platform": "slack",
                    "provider_message_id": "1700000000.000100",
                    "session_key": "agent:main:slack:channel:C1",
                    "channel_id": "C1",
                    "thread_id": "1700000000.000100",
                    "direction": "INBOUND",
                    "conversation_type": "CHANNEL",
                    "sender_id": "U1",
                    "sender_name": "Mauricio",
                    "channel_name": "support",
                    "content": "hello from Slack",
                    "occurred_at": observed_at,
                },
                {
                    "platform": "slack",
                    "provider_message_id": "outbound:obligation-1",
                    "session_key": "agent:main:slack:channel:C1",
                    "channel_id": "C1",
                    "thread_id": "1700000000.000100",
                    "direction": "OUTBOUND",
                    "conversation_type": "CHANNEL",
                    "content": "hello from Hermes",
                    "occurred_at": observed_at,
                },
            ],
        }

        with when("the observer reports an inbound message and its reply twice"):
            first = context.ingest_client.post(
                f"/ingest/v1/agents/{context.agent.id}/communication-events", json=payload, headers=_auth(context)
            )
            second = context.ingest_client.post(
                f"/ingest/v1/agents/{context.agent.id}/communication-events", json=payload, headers=_auth(context)
            )

        with then("the dashboard's conversation table has one message per provider message"):
            assert_that(first.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            assert_that(second.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
            with Session(delegate.engine) as session:
                messages = list(
                    session.exec(
                        select(AgentChatMessage)
                        .where(col(AgentChatMessage.connection_id) == context.connection.id)
                        .order_by(col(AgentChatMessage.openclaw_msg_id))
                    ).all()
                )
            assert_that(len(messages), equal_to(2))
            assert_that([message.content for message in messages], equal_to(["hello from Slack", "hello from Hermes"]))
            assert_that([message.direction for message in messages], equal_to([MessageDirection.INBOUND, MessageDirection.OUTBOUND]))
