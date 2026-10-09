from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid5, uuid7

from hamcrest import assert_that, contains_inanyorder, equal_to

from api.domains.analytics import message_counts
from api.domains.analytics.message_counts import MESSAGE_COUNT_EVENT, MessageCountReporter, previous_hour
from api.domains.analytics.repository import InstallationRepository
from api.domains.communications.models import CommunicationPlatform
from api.domains.conversations.models import AgentChatMessage, ConversationType, MessageDirection
from api.domains.conversations.repository import ConversationRepository, MessageCount
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.mocks.posthog import MockPostHogModule
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.communication import there_is_a_connection
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

HOUR = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
IN = MessageDirection.INBOUND
OUT = MessageDirection.OUTBOUND
WEB = CommunicationPlatform.WEB.value
TELEGRAM = CommunicationPlatform.TELEGRAM.value


def _given(posthog: MockPostHogModule, *, enabled: bool = True):
    return [
        set_env_variable(
            {
                "ANALYTICS_ENABLED": str(enabled).lower(),
                "INSTALLATION_NAME": "test-installation",
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            }
        ),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), posthog]),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        there_is_an_agent(),
        _two_connections_with_messages(),
    ]


def _message(connection, direction: MessageDirection, created_at: datetime, occurred_at: datetime | None = None):
    return AgentChatMessage(
        agent_id=connection.agent_id,
        connection_id=connection.id,
        openclaw_msg_id=str(uuid7()),
        session_key="session",
        channel_id="channel",
        direction=direction,
        conversation_type=ConversationType.DM,
        content="never sent to analytics",
        occurred_at=occurred_at or created_at,
        created_at=created_at,
    )


def _two_connections_with_messages():
    def step(context):
        there_is_a_connection(CommunicationPlatform.WEB)(context)
        web = context.connection
        there_is_a_connection(CommunicationPlatform.TELEGRAM)(context)
        telegram = context.connection
        inside = HOUR + timedelta(minutes=10)
        context.injector.get(PostgresRepositoryDelegate).save_all(
            [
                _message(web, IN, inside),
                _message(web, IN, inside),
                _message(web, OUT, inside),
                _message(telegram, IN, inside),
                _message(web, IN, HOUR + timedelta(hours=1)),
                _message(web, IN, HOUR + timedelta(hours=2), occurred_at=inside),
            ]
        )

    return step


def test_counts_one_closed_hour_per_agent_platform_and_direction_by_arrival_time():
    with given(_given(MockPostHogModule())) as context:
        counts = context.injector.get(ConversationRepository).hourly_message_counts(HOUR)

        agent, org = context.agent.id, context.agent.organization_id
        assert_that(
            counts,
            contains_inanyorder(
                MessageCount(agent, org, WEB, IN, 2),
                MessageCount(agent, org, WEB, OUT, 1),
                MessageCount(agent, org, TELEGRAM, IN, 1),
            ),
        )


def test_sends_one_count_per_row_as_the_installation_with_distinct_ids():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        sent = context.injector.get(MessageCountReporter).report(HOUR)

        installation_id = context.injector.get(InstallationRepository).get_id()
        captures = [message for batch in posthog.batches for message in batch]
        assert_that(sent, equal_to(3))
        assert_that(len({capture["uuid"] for capture in captures}), equal_to(3))
        web_inbound = next(
            c for c in captures if c["properties"]["platform"] == WEB and c["properties"]["direction"] == "INBOUND"
        )
        assert_that(
            web_inbound,
            equal_to(
                {
                    "event": MESSAGE_COUNT_EVENT,
                    "distinct_id": f"installation:{installation_id}",
                    "uuid": str(uuid5(installation_id, f"{context.agent.id}:{WEB}:INBOUND:{HOUR.isoformat()}")),
                    "timestamp": HOUR.isoformat(),
                    "properties": {
                        "agent_id": str(context.agent.id),
                        "platform": WEB,
                        "direction": "INBOUND",
                        "count": 2,
                        "organization_id": str(context.agent.organization_id),
                        "installation_id": str(installation_id),
                        "installation_name": "test-installation",
                        "$groups": {
                            "installation": str(installation_id),
                            "organization": str(context.agent.organization_id),
                        },
                        "source": "agentbarn-api",
                        "$geoip_disable": True,
                        "$lib": "agentbarn-api",
                        "$set": {"kind": "installation"},
                    },
                }
            ),
        )


def test_a_rerun_sends_the_same_ids():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        reporter = context.injector.get(MessageCountReporter)
        reporter.report(HOUR)
        reporter.report(HOUR)

        first, second = posthog.batches
        assert_that(sorted(m["uuid"] for m in second), equal_to(sorted(m["uuid"] for m in first)))


def test_large_hours_are_split_into_several_batches():
    posthog = MockPostHogModule()
    with given(_given(posthog)) as context:
        with patch.object(message_counts, "MAX_BATCH_SIZE", 2):
            context.injector.get(MessageCountReporter).report(HOUR)

        assert_that([len(batch) for batch in posthog.batches], equal_to([2, 1]))


def test_nothing_is_sent_while_analytics_is_disabled():
    posthog = MockPostHogModule()
    with given(_given(posthog, enabled=False)) as context:
        sent = context.injector.get(MessageCountReporter).report(HOUR)

        assert_that((sent, posthog.batches), equal_to((0, [])))


def test_the_previous_hour_is_the_last_closed_one():
    assert_that(previous_hour(datetime(2026, 10, 7, 10, 15, 42, tzinfo=UTC)), equal_to(HOUR))
