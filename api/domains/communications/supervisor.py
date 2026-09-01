import asyncio
import json
import logging
import time
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

_RETRY_BACKOFF_INITIAL_SECONDS = 1.0
_RETRY_BACKOFF_MAX_SECONDS = 60.0
# An ingress session that survived this long was genuinely connected; the next
# failure starts a fresh backoff sequence instead of continuing to climb.
_RETRY_BACKOFF_RESET_AFTER_SECONDS = 60.0


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
    _last_journal_prune_at: datetime = field(default_factory=lambda: datetime.min.replace(tzinfo=UTC), init=False)

    async def run(self, stop: asyncio.Event) -> None:
        tasks: dict[UUID, tuple[int, asyncio.Task[None]]] = {}
        try:
            while not stop.is_set():
                try:
                    await self._reconcile(tasks)
                except Exception:
                    # The supervisor is a process-lifetime singleton task: an
                    # unhandled error here (transient DB blip on list_enabled or
                    # a lease claim) would end run() and silently disable all
                    # platform ingress until the process restarts.
                    logger.exception("Communications ingress reconcile cycle failed; retrying")
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

    async def _reconcile(self, tasks: dict[UUID, tuple[int, asyncio.Task[None]]]) -> None:
        """One reconcile pass: prune the journal, then reconcile ingress tasks.

        Kept separate from ``run`` so a failed pass is logged and retried on the
        next cycle instead of ending the supervisor.
        """
        now = datetime.now(UTC)
        if self.operations is not None and now - self._last_journal_prune_at >= timedelta(minutes=5):
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
            self._last_journal_prune_at = now
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

    async def _maintain(self, connection: CommunicationConnection) -> None:
        backoff_seconds = _RETRY_BACKOFF_INITIAL_SECONDS
        while True:
            session_started_at = time.monotonic()
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

                if (
                    PlatformCapability.WEBHOOK_INGRESS in plugin.capabilities
                    or PlatformCapability.SUPERVISED_INGRESS not in plugin.capabilities
                ):
                    # Webhook-ingress plugins receive events out-of-band; plugins
                    # that declare neither capability (e.g. Web Chat) have
                    # nothing to supervise at all. Either way there is no
                    # session to run, so `run_ingress` is never called and its
                    # base-class NotImplementedError never surfaces as a fault.
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
                if time.monotonic() - session_started_at >= _RETRY_BACKOFF_RESET_AFTER_SECONDS:
                    backoff_seconds = _RETRY_BACKOFF_INITIAL_SECONDS
                # Repeated connection attempts belong in the journal and metrics,
                # not the Domain Event stream — so retries back off exponentially
                # rather than hammering at a flat 2s cadence.
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, _RETRY_BACKOFF_MAX_SECONDS)
