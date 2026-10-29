from datetime import datetime
from uuid import uuid7

from api.domains.communications.models import CommunicationConnection
from api.domains.conversations.models import AgentChatMessage, MessageDirection


def there_is_a_recorded_message(
    occurred_at: datetime,
    direction: MessageDirection = MessageDirection.INBOUND,
    platform_key: str = "slack",
):
    def step(context):
        connection = CommunicationConnection(
            organization_id=context.agent.organization_id,
            agent_id=context.agent.id,
            platform_key=platform_key,
            display_name=f"Test {platform_key} connection",
            credentials_encrypted="test",
            driver_key_encrypted="test",
        )
        context.postgres_delegate.save(connection)
        message = AgentChatMessage(
            agent_id=context.agent.id,
            connection_id=connection.id,
            openclaw_msg_id=str(uuid7()),
            session_key="test-session",
            channel_id="test-channel",
            direction=direction,
            content="Message content must not appear in the Agent list",
            occurred_at=occurred_at,
        )
        context.postgres_delegate.save(message)

    return step
