import argparse
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

from injector import inject, singleton

from api.core.config import Config
from api.domains.analytics.event_handlers import INSTALLATION_GROUP, ORGANIZATION_GROUP, SOURCE
from api.domains.analytics.repository import InstallationRepository
from api.domains.conversations.repository import ConversationRepository, MessageCount
from api.infrastructure.posthog.client import PostHogClient

logger = logging.getLogger(__name__)

MESSAGE_COUNT_EVENT = "agent.messages.counted"
MAX_BATCH_SIZE = 500


def previous_hour(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)


@inject
@singleton
@dataclass
class MessageCountReporter:
    config: Config
    conversation_repository: ConversationRepository
    installation_repository: InstallationRepository
    posthog_client: PostHogClient

    def report(self, hour_start: datetime) -> int:
        if not self.config.is_analytics_enabled:
            return 0
        installation_id = self.installation_repository.get_id()
        messages = [
            self._message(row, hour_start, installation_id)
            for row in self.conversation_repository.hourly_message_counts(hour_start)
        ]
        for start in range(0, len(messages), MAX_BATCH_SIZE):
            self.posthog_client.send_batch(messages[start : start + MAX_BATCH_SIZE])
        logger.info("Message counts sent: hour=%s events=%s", hour_start.isoformat(), len(messages))
        return len(messages)

    @staticmethod
    def _message(row: MessageCount, hour_start: datetime, installation_id: UUID) -> dict[str, Any]:
        direction = row.direction.value
        return {
            "event": MESSAGE_COUNT_EVENT,
            "distinct_id": f"installation:{installation_id}",
            "uuid": str(uuid5(installation_id, f"{row.agent_id}:{row.platform}:{direction}:{hour_start.isoformat()}")),
            "timestamp": hour_start.isoformat(),
            "properties": {
                "agent_id": str(row.agent_id),
                "platform": row.platform,
                "direction": direction,
                "count": row.count,
                "organization_id": str(row.organization_id),
                "installation_id": str(installation_id),
                "$groups": {INSTALLATION_GROUP: str(installation_id), ORGANIZATION_GROUP: str(row.organization_id)},
                "source": SOURCE,
                "$geoip_disable": True,
                "$lib": SOURCE,
                "$set": {"kind": "installation"},
            },
        }


def main() -> None:
    from api.core.utils import create_injector

    argparse.ArgumentParser(description="Send the previous hour's message counts to product analytics.").parse_args()
    logging.basicConfig(level=logging.INFO)
    create_injector().get(MessageCountReporter).report(previous_hour(datetime.now(UTC)))
