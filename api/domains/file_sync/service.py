from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.file_sync.engine import delete_agent_folder, sync_root
from api.domains.file_sync.models import AgentFileSyncSettingRead
from api.domains.file_sync.repository import AgentFileSyncRepository, FileSyncRepository
from api.domains.rbac.catalog import PermissionKey
from api.domains.sync_provider.models import SyncProviderConnection
from api.domains.sync_provider.plugins.base import SyncProviderPlugin

DISCONNECT_LOCK_WAIT_SECONDS = 15


class FileSyncBusy(Exception):
    pass


@inject
@singleton
@dataclass
class FileSyncFolderRemoval:
    repository: FileSyncRepository

    @contextmanager
    def holding(self, connection_id: UUID) -> Iterator[None]:
        with self.repository.connection_lock(connection_id, wait_seconds=DISCONNECT_LOCK_WAIT_SECONDS) as acquired:
            if not acquired:
                raise FileSyncBusy
            yield

    def remove_agent_folders(self, connection: SyncProviderConnection, plugin: SyncProviderPlugin) -> None:
        root = sync_root(connection)
        for folder in self.repository.folders(connection.id):
            delete_agent_folder(plugin, root, self.repository, folder)


@inject
@singleton
@dataclass
class AgentFileSyncService:
    repository: AgentFileSyncRepository
    authorization: AgentAuthorization
    event_delivery_dispatcher: EventDeliveryDispatcher

    def set_enabled(self, agent_id: UUID, enabled: bool, context: CurrentUserContext) -> AgentFileSyncSettingRead:
        agent = self.authorization.require_action(
            context,
            agent_id,
            PermissionKey.AGENT_UPDATE,
            detail="You don't have permission to change file sync for this Agent.",
        )
        delivery_ids = self.repository.set_enabled_with_event(
            agent.id,
            agent.organization_id,
            enabled,
            actor=resolve_actor_identity(context, agent.organization_id),
            actor_display=context.user.full_name or context.user.email,
            now=datetime.now(UTC),
        )
        if delivery_ids is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
        return AgentFileSyncSettingRead(agent_id=agent.id, enabled=enabled)
