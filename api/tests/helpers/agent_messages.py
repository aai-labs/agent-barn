"""Communication runtime setup shared by initiated-delivery scenarios."""

import json
from datetime import UTC, datetime
from uuid import UUID

from hamcrest import assert_that, equal_to
from sqlmodel import Session, col, select

from api.domains.agents.models import AgentStatus
from api.domains.communications.models import CommunicationConnection, CommunicationDelivery, CommunicationJournalEntry
from api.domains.conversations.models import AgentChatMessage, ConversationType, MessageDirection
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_communications_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

STEPS = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "SKIP_SLACK_TOKEN_VALIDATION": "true",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    prepare_communications_server(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(status=AgentStatus.RUNNING),
]


def messaging_ready(context):
    delegate = context.injector.get(PostgresRepositoryDelegate)
    context.agent.communication_key_encrypted = encrypt_token("runtime-key", TEST_ENCRYPTION_KEY)
    delegate.save(context.agent)
    context.connection = CommunicationConnection(
        organization_id=context.agent.organization_id,
        agent_id=context.agent.id,
        platform_key="slack",
        display_name="Slack",
        enabled=True,
        settings={"channel_ids": ["C123", "C456"], "default_delivery_target": {"kind": "channel", "recipient": "C123"}},
        credentials_encrypted=encrypt_token(
            json.dumps({"bot_token": "xoxb-test", "app_token": "xapp-test"}), TEST_ENCRYPTION_KEY
        ),
        driver_key_encrypted="unused",
    )
    delegate.save(context.connection)
    context.runtime_headers = {"Authorization": "Bearer runtime-key", "X-AgentBarn-Communications-Version": "2"}


def scheduled_request(key="run-one", text="Scheduled result"):
    return {
        "text": text,
        "idempotency_key": key,
        "destination": {"kind": "default"},
        "context": {"kind": "scheduled", "run_id": "hermes:run-one"},
    }


def origin_request(context, connection=None, channel="C456", thread=None, key="run-origin"):
    return {
        "text": "Scheduled result",
        "idempotency_key": key,
        "destination": {
            "kind": "origin",
            "connection_id": str((connection or context.connection).id),
            "channel_id": channel,
            "thread_id": thread,
        },
        "context": {"kind": "scheduled", "run_id": "hermes:run-origin"},
    }


def agent_was_in_conversation(context, connection=None, channel="C456", conversation_type=ConversationType.CHANNEL):
    """Canonical history for a channel, which is what proves the Agent was really there."""
    delegate = context.injector.get(PostgresRepositoryDelegate)
    delegate.save(
        AgentChatMessage(
            agent_id=context.agent.id,
            connection_id=(connection or context.connection).id,
            openclaw_msg_id=f"inbound:{channel}",
            session_key=f"seed:{channel}",
            channel_id=channel,
            channel_name="updates",
            direction=MessageDirection.INBOUND,
            conversation_type=conversation_type,
            content="schedule a daily summary here",
            occurred_at=datetime.now(UTC),
        )
    )


def submit(context, payload):
    return context.communications_client.post(
        f"/communications/v1/agents/{context.agent.id}/messages", headers=context.runtime_headers, json=payload
    )


def rows(context):
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return (
            session.exec(
                select(CommunicationDelivery).where(col(CommunicationDelivery.agent_id) == context.agent.id)
            ).all(),
            session.exec(select(AgentChatMessage).where(col(AgentChatMessage.agent_id) == context.agent.id)).all(),
            session.exec(
                select(CommunicationJournalEntry).where(col(CommunicationJournalEntry.agent_id) == context.agent.id)
            ).all(),
        )


def change_connection(context, **changes):
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        connection = session.get(CommunicationConnection, context.connection.id)
        for key, value in changes.items():
            setattr(connection, key, value)
        connection.revision += 1
        session.add(connection)
        session.commit()


def receipt_id(response):
    assert_that(response.status_code, equal_to(202), response.text)
    return UUID(response.json()["delivery_id"])


def second_slack_connection(context):
    """A second Slack workspace on the same Agent, which a send must never leak into."""
    delegate = context.injector.get(PostgresRepositoryDelegate)
    connection = CommunicationConnection(
        organization_id=context.agent.organization_id,
        agent_id=context.agent.id,
        platform_key="slack",
        display_name="Other Slack",
        enabled=True,
        settings={"channel_ids": ["C456"]},
        credentials_encrypted=encrypt_token(
            json.dumps({"bot_token": "xoxb-other", "app_token": "xapp-other"}), TEST_ENCRYPTION_KEY
        ),
        driver_key_encrypted="unused",
    )
    delegate.save(connection)
    return connection
