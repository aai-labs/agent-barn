import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.communications.error_details import normalize_communication_error
from api.domains.communications.models import ConnectionObservedStatus
from api.domains.communications.operations import CommunicationOperationalRepository
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.repository import CommunicationConnectionRepository
from api.infrastructure.crypto import decrypt_token

logger = logging.getLogger(__name__)
_EMAIL_BATCH_SIZE = 100
_JOURNAL_BATCH_SIZE = 2500


@inject
@singleton
@dataclass
class CommunicationsMaintenance:
    """Bounded configuration health and retention work, without provider sessions."""

    config: Config
    connections: CommunicationConnectionRepository
    plugins: PlatformPluginRegistry
    operations: CommunicationOperationalRepository
    _email_cursor: UUID | None = field(default=None, init=False)
    _next_journal_prune_at: datetime = field(default_factory=lambda: datetime.min.replace(tzinfo=UTC), init=False)

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self._reconcile()
            except Exception:
                logger.exception("Communications maintenance cycle failed; retrying")
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                pass

    async def _reconcile(self) -> None:
        now = datetime.now(UTC)
        if now >= self._next_journal_prune_at:
            try:
                removed = await asyncio.to_thread(
                    self.operations.prune_journal,
                    retention_days=self.config.communication_journal_retention_days,
                    batch_size=_JOURNAL_BATCH_SIZE,
                )
                if removed < _JOURNAL_BATCH_SIZE:
                    self._next_journal_prune_at = now + timedelta(minutes=5)
            except Exception:
                logger.exception("Communication journal retention sweep failed; retrying")
        connections = await asyncio.to_thread(
            self.connections.list_enabled_email_page, after_id=self._email_cursor, limit=_EMAIL_BATCH_SIZE
        )
        for connection in connections:
            status = ConnectionObservedStatus.CONNECTED
            error = None
            try:
                plugin = self.plugins.require("email")
                plugin.validate_configuration(
                    connection.settings,
                    json.loads(decrypt_token(connection.credentials_encrypted, self.config.agent_token_encryption_key)),
                    organization_id=connection.organization_id,
                    agent_id=connection.agent_id,
                )
            except Exception as exc:
                status = ConnectionObservedStatus.ERROR
                error = normalize_communication_error(exc, operation="email_configuration")
            await asyncio.to_thread(
                self.connections.record_health,
                connection.id,
                status,
                expected_revision=connection.revision,
                error_code=error.code if error else None,
                error_message=error.summary if error else None,
                error_details=error.details if error else None,
            )
        self._email_cursor = connections[-1].id if len(connections) == _EMAIL_BATCH_SIZE else None
