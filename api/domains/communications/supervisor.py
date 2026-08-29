import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from injector import inject, singleton

from api.core.config import Config
from api.domains.communications.error_details import normalize_communication_error
from api.domains.communications.gateway_service import CommunicationsGatewayService
from api.domains.communications.models import (
    CommunicationConnection,
    ConnectionObservedStatus,
    PlatformCapability,
)
from api.domains.communications.operations import CommunicationOperationalRepository
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.repository import CommunicationConnectionRepository
from api.infrastructure.crypto import decrypt_token

logger = logging.getLogger(__name__)


@inject
@singleton
@dataclass
class PlatformIngressSupervisor:
    """Reconciles enabled Connections into isolated provider ingress tasks."""

    config: Config
    connections: CommunicationConnectionRepository
    gateway: CommunicationsGatewayService
    plugins: PlatformPluginRegistry
    operations: CommunicationOperationalRepository | None = None
    owner_id: str = field(default_factory=lambda: str(uuid4()), init=False)

    async def run(self, stop: asyncio.Event) -> None:
        tasks: dict[UUID, tuple[int, asyncio.Task[None]]] = {}
        last_journal_prune_at = datetime.min.replace(tzinfo=UTC)
        try:
            while not stop.is_set():
                now = datetime.now(UTC)
                if self.operations is not None and now - last_journal_prune_at >= timedelta(minutes=5):
                    try:
                        await asyncio.to_thread(
                            self.operations.prune_journal,
                            retention_days=self.config.communication_journal_retention_days,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Communication journal retention sweep failed (%s)",
                            type(exc).__name__,
                        )
                    last_journal_prune_at = now
                enabled_connections = await asyncio.to_thread(self.connections.list_enabled)
                enabled = {connection.id: connection for connection in enabled_connections}
                for connection_id, (revision, task) in list(tasks.items()):
                    current = enabled.get(connection_id)
                    lease_held = current is not None and await asyncio.to_thread(
                        self.connections.claim_ingress_lease,
                        connection_id,
                        self.owner_id,
                    )
                    if current is None or current.revision != revision or task.done() or not lease_held:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        await asyncio.to_thread(
                            self.connections.release_ingress_lease,
                            connection_id,
                            self.owner_id,
                        )
                        tasks.pop(connection_id)
                for connection in enabled.values():
                    lease_claimed = connection.id not in tasks and await asyncio.to_thread(
                        self.connections.claim_ingress_lease,
                        connection.id,
                        self.owner_id,
                    )
                    if lease_claimed:
                        tasks[connection.id] = (
                            connection.revision,
                            asyncio.create_task(
                                self._maintain(connection),
                                name=f"communications-{connection.platform_key}-{connection.id}",
                            ),
                        )
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5)
                except TimeoutError:
                    pass
        finally:
            for _, task in tasks.values():
                task.cancel()
            await asyncio.gather(*(task for _, task in tasks.values()), return_exceptions=True)
            await asyncio.gather(
                *(
                    asyncio.to_thread(self.connections.release_ingress_lease, connection_id, self.owner_id)
                    for connection_id in tasks
                )
            )

    async def _maintain(self, connection: CommunicationConnection) -> None:
        while True:
            await asyncio.to_thread(
                self.connections.record_health,
                connection.id,
                ConnectionObservedStatus.CONNECTING,
            )
            try:
                plugin = self.plugins.require(connection.platform_key)
                settings = plugin.settings_model.model_validate(connection.settings)
                credentials = plugin.credentials_model.model_validate(
                    json.loads(
                        decrypt_token(
                            connection.credentials_encrypted,
                            self.config.agent_token_encryption_key,
                        )
                    )
                )

                async def emit(payload: dict) -> None:
                    await asyncio.to_thread(self.gateway.accept_plugin_payload, connection.id, payload)

                async def connected() -> None:
                    await asyncio.to_thread(
                        self.connections.record_health,
                        connection.id,
                        ConnectionObservedStatus.CONNECTED,
                    )

                if PlatformCapability.WEBHOOK_INGRESS in plugin.capabilities:
                    await connected()
                    await asyncio.Event().wait()

                await plugin.run_ingress(settings, credentials, emit, connected)
                raise RuntimeError("Platform ingress session ended unexpectedly")
            except NotImplementedError as exc:
                normalized_error = normalize_communication_error(
                    exc,
                    error_code="INGRESS_NOT_SUPERVISED",
                    operation="ingress_session",
                )
                await asyncio.to_thread(
                    self.connections.record_health,
                    connection.id,
                    ConnectionObservedStatus.DEGRADED,
                    error_code=normalized_error.code,
                    error_message=normalized_error.summary,
                    error_details=normalized_error.details,
                )
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Communication Connection %s ingress failed (%s)", connection.id, type(exc).__name__)
                normalized_error = normalize_communication_error(exc, operation="ingress_session")
                await asyncio.to_thread(
                    self.connections.record_health,
                    connection.id,
                    ConnectionObservedStatus.ERROR,
                    error_code=normalized_error.code,
                    error_message=normalized_error.summary,
                    error_details=normalized_error.details,
                )
                await asyncio.sleep(2)
