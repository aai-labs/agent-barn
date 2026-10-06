import json
from datetime import UTC, datetime, timedelta
from itertools import count

import httpx
from hamcrest import assert_that, contains_exactly, equal_to, has_properties, none
from sqlmodel import Session, col, select

from api.domains.agents.models import AgentStatus
from api.domains.communications.agentbarn_telegram_forwarder import AgentBarnTelegramForwarder
from api.domains.communications.agentbarn_telegram_repository import AgentBarnTelegramRepository
from api.domains.communications.models import (
    AgentBarnTelegramUpdate,
    AgentBarnTelegramUpdateStatus,
    CommunicationConnection,
)
from api.domains.communications.plugins.agentbarn_telegram import runtime_webhook_secret
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_JANE = 5550001
_SAM = 7770007
_DRIVER_KEY = "driver-key-for-the-test-connection"


class RecordingBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    def send(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


class Pod:
    """The Agent pod's webhook listener: answers with the next status, recording what it received."""

    def __init__(self, *statuses: int | Exception) -> None:
        self.statuses = list(statuses)
        self.received: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.received.append(request)
        outcome = self.statuses.pop(0) if self.statuses else 200
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome)

    def texts(self) -> list[str]:
        return [json.loads(request.content)["message"]["text"] for request in self.received]


def _agent(status: AgentStatus):
    def step(context):
        there_is_an_agent(name="Sales Helper", status=status)(context)
        context.connection = CommunicationConnection(
            organization_id=context.agent.organization_id,
            agent_id=context.agent.id,
            platform_key="agentbarn_telegram",
            display_name="Agent Barn Telegram",
            credentials_encrypted="unused",
            driver_key_encrypted=encrypt_token(_DRIVER_KEY, TEST_ENCRYPTION_KEY),
        )
        context.injector.get(PostgresRepositoryDelegate).save(context.connection)
        context.bot = RecordingBot()
        context.injector.get(AgentBarnTelegramForwarder).bot = context.bot

    return step


def _given(status: AgentStatus = AgentStatus.RUNNING) -> list:
    return [
        set_env_variable(
            {
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "AGENTBARN_TELEGRAM_RUNTIME_WEBHOOK_URL": "http://agent-{agent_id}.{namespace}.test:8443/telegram",
                "K8S_NAMESPACE": "trials",
            }
        ),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        _agent(status),
    ]


_update_ids = count(20_000)


def _queue(context, text: str, user: int = _JANE, *, received_at: datetime | None = None) -> int:
    update_id = next(_update_ids)
    update = {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "from": {"id": user, "is_bot": False},
            "chat": {"id": user, "type": "private"},
            "text": text,
        },
    }
    repository = context.injector.get(AgentBarnTelegramRepository)
    repository.store_updates([update])
    repository.queue_update(
        update_id, telegram_user_id=user, agent_id=context.agent.id, connection_id=context.connection.id
    )
    if received_at is not None:
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            row = session.exec(
                select(AgentBarnTelegramUpdate).where(col(AgentBarnTelegramUpdate.update_id) == update_id)
            ).one()
            row.created_at = received_at
            session.add(row)
            session.commit()
    return update_id


def _forward(context, pod: Pod, now: datetime | None = None) -> None:
    forwarder = context.injector.get(AgentBarnTelegramForwarder)
    forwarder.client = httpx.Client(transport=httpx.MockTransport(pod))
    forwarder.forward_due(now=now or datetime.now(UTC))


def _row(context, update_id: int) -> AgentBarnTelegramUpdate:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return session.exec(
            select(AgentBarnTelegramUpdate).where(col(AgentBarnTelegramUpdate.update_id) == update_id)
        ).one()


def test_a_queued_message_reaches_its_agent_with_the_connection_secret() -> None:
    with given(_given()) as context:
        update_id = _queue(context, "What's on today?")
        pod = Pod(200)

        with when("the forwarder runs"):
            _forward(context, pod)

        with then("the agent's pod receives the original update, authenticated, and its content is dropped here"):
            request = pod.received[0]
            assert_that(str(request.url), equal_to(f"http://agent-{context.agent.id}.trials.test:8443/telegram"))
            assert_that(
                request.headers["X-Telegram-Bot-Api-Secret-Token"], equal_to(runtime_webhook_secret(_DRIVER_KEY))
            )
            assert_that(json.loads(request.content)["update_id"], equal_to(update_id))
            assert_that(
                _row(context, update_id), has_properties(status=AgentBarnTelegramUpdateStatus.FORWARDED, payload=none())
            )
            assert_that(context.bot.sent, equal_to([]))


def test_a_users_messages_arrive_in_order_and_wait_behind_a_failed_one() -> None:
    with given(_given()) as context:
        _queue(context, "first")
        _queue(context, "second")
        _queue(context, "hello from sam", user=_SAM)
        pod = Pod(503, 200)

        with when("the pod rejects Jane's first message, then everything is retried later"):
            _forward(context, pod)
            after_failure = pod.texts()
            _forward(context, pod, now=datetime.now(UTC) + timedelta(minutes=1))

        with then("Sam is not held up, and Jane's messages arrive in the order she sent them"):
            assert_that(after_failure, equal_to(["first", "hello from sam"]))
            assert_that(pod.texts(), equal_to(["first", "hello from sam", "first", "second"]))


def test_a_slow_start_tells_the_user_once_that_their_agent_is_waking_up() -> None:
    with given(_given()) as context:
        received_at = datetime.now(UTC)
        _queue(context, "hello", received_at=received_at)
        pod = Pod(httpx.ConnectError("refused"), httpx.ConnectError("refused"), httpx.ConnectError("refused"))

        with when("the pod is unreachable right away, after 15 seconds, and after a minute"):
            _forward(context, pod, now=received_at)
            quiet_at_first = list(context.bot.sent)
            _forward(context, pod, now=received_at + timedelta(seconds=15))
            _forward(context, pod, now=received_at + timedelta(minutes=1))

        with then("the user hears once, after the short grace period, that their agent is waking up"):
            assert_that(quiet_at_first, equal_to([]))
            assert_that(
                context.bot.sent,
                contains_exactly((_JANE, "Your agent is waking up. I'll pass your message on in a moment.")),
            )


def test_a_stopped_agent_is_not_contacted_and_the_user_hears_once_that_it_is_offline() -> None:
    with given(_given(AgentStatus.STOPPED)) as context:
        update_id = _queue(context, "hello")
        _queue(context, "anyone there?")
        pod = Pod()

        with when("the forwarder runs twice"):
            _forward(context, pod)
            _forward(context, pod, now=datetime.now(UTC) + timedelta(minutes=5))

        with then("nothing is sent to the pod, the messages wait, and the user is told once"):
            assert_that(pod.received, equal_to([]))
            assert_that(_row(context, update_id).status, equal_to(AgentBarnTelegramUpdateStatus.QUEUED))
            assert_that(
                context.bot.sent,
                contains_exactly((_JANE, "This agent is offline right now. I'll pass your message on when it's back.")),
            )


def test_messages_waiting_over_a_day_are_dropped_with_one_note() -> None:
    with given(_given(AgentStatus.STOPPED)) as context:
        long_ago = datetime.now(UTC) - timedelta(hours=25)
        first = _queue(context, "hello", received_at=long_ago)
        second = _queue(context, "hello again", received_at=long_ago)

        with when("the forwarder runs"):
            _forward(context, Pod())

        with then("both are dropped without their content, and the user is told once to send them again"):
            for update_id in (first, second):
                assert_that(
                    _row(context, update_id),
                    has_properties(status=AgentBarnTelegramUpdateStatus.DROPPED, payload=none()),
                )
            assert_that(
                context.bot.sent,
                contains_exactly(
                    (
                        _JANE,
                        (
                            "I couldn't reach your agent for over a day, so your 2 messages weren't delivered. "
                            "Please send them again."
                        ),
                    )
                ),
            )


def test_messages_for_a_connection_no_longer_in_use_are_dropped_silently() -> None:
    with given(_given()) as context:
        update_id = _queue(context, "hello")
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            connection = session.get(CommunicationConnection, context.connection.id)
            assert connection is not None
            connection.retired_at = datetime.now(UTC)
            session.add(connection)
            session.commit()
        pod = Pod()

        with when("the forwarder runs"):
            _forward(context, pod)

        with then("the message is dropped without contacting the pod or the user"):
            assert_that(pod.received, equal_to([]))
            assert_that(_row(context, update_id).status, equal_to(AgentBarnTelegramUpdateStatus.DROPPED))
            assert_that(context.bot.sent, equal_to([]))


def test_a_single_dropped_message_is_described_as_one() -> None:
    with given(_given(AgentStatus.STOPPED)) as context:
        _queue(context, "hello", received_at=datetime.now(UTC) - timedelta(hours=25))

        with when("the forwarder runs"):
            _forward(context, Pod())

        with then("the note speaks of one message"):
            assert_that(
                context.bot.sent,
                contains_exactly(
                    (
                        _JANE,
                        (
                            "I couldn't reach your agent for over a day, so your message wasn't delivered. "
                            "Please send it again."
                        ),
                    )
                ),
            )


def test_a_running_agent_that_rejects_messages_is_not_described_as_waking_up() -> None:
    with given(_given()) as context:
        received_at = datetime.now(UTC)
        update_id = _queue(context, "hello", received_at=received_at)
        pod = Pod(403, 403)

        with when("the agent's webhook keeps refusing the message"):
            _forward(context, pod, now=received_at)
            _forward(context, pod, now=received_at + timedelta(seconds=15))

        with then("the message keeps waiting for a retry, but the user is not told the agent is starting"):
            assert_that(_row(context, update_id).status, equal_to(AgentBarnTelegramUpdateStatus.QUEUED))
            assert_that(context.bot.sent, equal_to([]))
