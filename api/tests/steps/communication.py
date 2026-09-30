from datetime import UTC, datetime, timedelta
from uuid import uuid4, uuid7

import sqlalchemy as sa
from sqlmodel import Session, col

from api.domains.agent_webhooks.models import (
    AgentWebhook,
    WebhookDeliveryPlatform,
    WebhookInvocation,
    WebhookInvocationStatus,
)
from api.domains.agents.repository import AgentRepository
from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.models import (
    CommunicationConnection,
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    CommunicationDirection,
    CommunicationPlatform,
    CommunicationSender,
    ConversationLocation,
    NormalizedCommunicationEnvelope,
)
from api.domains.conversations.models import AgentChatMessage, MessageDirection
from api.domains.conversations.repository import ConversationRepository
from api.domains.events.models import ActorIdentity, ActorIdentityType
from api.domains.tool_calls.models import ToolCall, ToolCallStatus
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

DEFAULT_MINUTES_AGO = 5
SEEDED_CHANNEL_ID = "CHANNEL:C1"
SEEDED_SENDER_ID = "U1"
SEEDED_TEXT = "hello"
SEEDED_TOOL_NAME = "search"
SEEDED_PROMPT = "Summarise the ticket"


def _default_time() -> datetime:
    return datetime.now(UTC) - timedelta(minutes=DEFAULT_MINUTES_AGO)


def _delegate(context) -> PostgresRepositoryDelegate:
    return context.injector.get(PostgresRepositoryDelegate)


def there_is_a_connection(platform: CommunicationPlatform = CommunicationPlatform.WEB):
    def step(context):
        agent = context.agent
        connection = CommunicationConnection(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            platform_key=platform.value,
            display_name=f"{platform.value} {uuid7()}",
            credentials_encrypted="test-credentials",
            driver_key_encrypted="test-driver-key",
        )
        _delegate(context).save(connection)
        context.connection = connection

    return step


def there_is_an_inbound_delivery(
    *,
    occurred_at: datetime | None = None,
    status: CommunicationDeliveryStatus | None = None,
    attempt_count: int | None = None,
    created_at: datetime | None = None,
    completed_at: datetime | None = None,
):
    def step(context):
        at = occurred_at if occurred_at is not None else _default_time()
        accepted = context.injector.get(CommunicationDeliveryRepository).accept_inbound(
            connection_id=context.connection.id,
            envelope=NormalizedCommunicationEnvelope(
                provider_message_id=f"in-{uuid4().hex}",
                occurred_at=at,
                location=ConversationLocation(id=SEEDED_CHANNEL_ID, type="CHANNEL", display_name="general"),
                sender=CommunicationSender(id=SEEDED_SENDER_ID, display_name="Sender"),
                text=SEEDED_TEXT,
            ),
        )
        overrides = {
            name: value
            for name, value in {
                "status": status,
                "attempt_count": attempt_count,
                "created_at": created_at,
                "completed_at": completed_at,
            }.items()
            if value is not None
        }
        if overrides:
            with Session(_delegate(context).engine) as session:
                session.exec(  # type: ignore[call-overload]
                    sa.update(CommunicationDelivery)
                    .where(col(CommunicationDelivery.id) == accepted.delivery_id)
                    .values(**overrides)
                )
                session.commit()
        context.delivery_id = accepted.delivery_id

    return step


def there_is_an_outbound_delivery(*, completed_at: datetime | None = None):
    def step(context):
        at = completed_at if completed_at is not None else _default_time()
        agent = context.agent
        message = AgentChatMessage(
            agent_id=agent.id,
            connection_id=context.connection.id,
            openclaw_msg_id=f"outbound:{uuid4().hex}",
            session_key="session-1",
            channel_id=SEEDED_CHANNEL_ID,
            direction=MessageDirection.OUTBOUND,
            content=SEEDED_TEXT,
            occurred_at=at,
        )
        delivery = CommunicationDelivery(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            connection_id=context.connection.id,
            message_id=message.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationDeliveryStatus.SUCCEEDED,
            idempotency_key=f"out-{uuid4().hex}",
            ordering_key=f"out-{uuid4().hex}",
            attempt_count=1,
            available_at=at,
            completed_at=at,
            envelope={},
        )
        with Session(_delegate(context).engine) as session:
            session.add(message)
            session.flush()
            session.add(delivery)
            session.commit()

    return step


def there_is_a_message(*, direction: MessageDirection = MessageDirection.INBOUND, occurred_at: datetime | None = None):
    def step(context):
        at = occurred_at if occurred_at is not None else _default_time()
        context.injector.get(ConversationRepository).upsert_messages(
            [
                AgentChatMessage(
                    agent_id=context.agent.id,
                    connection_id=context.connection.id,
                    openclaw_msg_id=f"msg-{uuid4().hex}",
                    session_key="session-1",
                    channel_id=SEEDED_CHANNEL_ID,
                    direction=direction,
                    sender_id=SEEDED_SENDER_ID,
                    content=SEEDED_TEXT,
                    occurred_at=at,
                )
            ]
        )

    return step


def there_is_a_webhook_invocation(
    *,
    created_at: datetime | None = None,
    status: WebhookInvocationStatus = WebhookInvocationStatus.SUBMITTED,
):
    def step(context):
        agent = context.agent
        webhook = AgentWebhook(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            display_name=f"Webhook {uuid7()}",
            delivery_platform=WebhookDeliveryPlatform.SLACK,
            signing_secret_encrypted="test-secret",
        )
        invocation = WebhookInvocation(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            webhook_id=webhook.id,
            prompt=SEEDED_PROMPT,
            status=status,
            created_at=created_at if created_at is not None else _default_time(),
        )
        with Session(_delegate(context).engine) as session:
            session.add(webhook)
            session.flush()
            session.add(invocation)
            session.commit()

    return step


def there_are_tool_calls(
    *,
    count: int = 1,
    occurred_at: datetime | None = None,
    status: ToolCallStatus = ToolCallStatus.SUCCESS,
):
    def step(context):
        at = occurred_at if occurred_at is not None else _default_time()
        agent = context.agent
        with Session(_delegate(context).engine) as session:
            session.add_all(
                [
                    ToolCall(
                        organization_id=agent.organization_id,
                        agent_id=agent.id,
                        session_id="session-1",
                        external_id=f"tc-{uuid4().hex}",
                        tool_name=SEEDED_TOOL_NAME,
                        arguments={},
                        status=status,
                        occurred_at=at,
                    )
                    for _ in range(count)
                ]
            )
            session.commit()

    return step


def the_agent_is_soft_deleted():
    def step(context):
        context.injector.get(AgentRepository).soft_delete_with_event(
            context.agent,
            actor=ActorIdentity(type=ActorIdentityType.USER, id=uuid7()),
        )

    return step


def the_connection_is_retired():
    def step(context):
        with Session(_delegate(context).engine) as session:
            session.exec(  # type: ignore[call-overload]
                sa.update(CommunicationConnection)
                .where(col(CommunicationConnection.id) == context.connection.id)
                .values(retired_at=datetime.now(UTC))
            )
            session.commit()

    return step
