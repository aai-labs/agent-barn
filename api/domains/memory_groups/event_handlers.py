import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from injector import inject

from api.domains.events.catalog import MEMORY_GROUP_DELETED, MEMORY_POOL_PURGE_HANDLER
from api.domains.events.handlers import (
    EventDeliveryContext,
    RetryableEventHandlerError,
    SupportedEvent,
)
from api.domains.events.models import DomainEventEnvelope
from api.infrastructure.honcho.client import HonchoClient, HonchoError

logger = logging.getLogger(__name__)


@inject
@dataclass
class MemoryPoolPurgeHandler:
    """Durably erases a memory group's shared Honcho pool when the group is deleted.

    Honcho deletes a workspace's sessions asynchronously and 409s the workspace
    delete while any still linger, so a single pass usually fails. Running this as a
    retried domain-event delivery (rather than a one-shot in the delete request)
    drives the erase to completion past that race: each attempt re-drains the
    sessions and retries the workspace delete, and a workspace that never existed
    404s and counts as already gone (idempotent). A transient Honcho failure raises
    `RetryableEventHandlerError` so the delivery is rescheduled with backoff.
    """

    honcho: HonchoClient

    name: ClassVar[str] = MEMORY_POOL_PURGE_HANDLER
    supported_events: ClassVar[Sequence[SupportedEvent]] = (SupportedEvent(MEMORY_GROUP_DELETED, 1),)

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None:
        workspace_id = str(event.payload["workspace_id"])
        try:
            self.honcho.delete_pool_workspace(workspace_id)
        except HonchoError as exc:
            raise RetryableEventHandlerError(f"Could not erase memory pool {workspace_id}: {exc}") from exc
