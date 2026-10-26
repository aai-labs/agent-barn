from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent, AgentStatus
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.file_sync.engine import delete_agent_folder, sync_root
from api.domains.file_sync.models import (
    AgentFileSyncActivityRead,
    AgentFileSyncProviderRead,
    AgentFileSyncRead,
    AgentFileSyncSettingRead,
    AgentFileSyncState,
    SyncAgentFolder,
    SyncFolderStatus,
)
from api.domains.file_sync.repository import AgentFileSyncRepository, FileSyncRepository
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import AuthorizationScope
from api.domains.sync_provider.models import SyncProviderCapability, SyncProviderConnection
from api.domains.sync_provider.plugins.base import SyncProviderPlugin
from api.domains.sync_provider.plugins.registry import SyncProviderPluginRegistry
from api.infrastructure.shared.models import PaginatedItems, Pagination

DISCONNECT_LOCK_WAIT_SECONDS = 15
NOT_SYNCING_AFTER = timedelta(minutes=10)


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
    plugins: SyncProviderPluginRegistry

    def status(self, agent_id: UUID, context: CurrentUserContext) -> AgentFileSyncRead:
        agent, scope = self._readable(agent_id, context)
        found = self.repository.status_inputs(agent.id, scope)
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
        current, connection, folder = found
        return self._status(current, connection, folder, datetime.now(UTC))

    def activity(
        self, agent_id: UUID, pagination: Pagination, context: CurrentUserContext
    ) -> PaginatedItems[AgentFileSyncActivityRead]:
        agent, scope = self._readable(agent_id, context)
        return self.repository.activity_page(agent.id, pagination, scope)

    def _readable(self, agent_id: UUID, context: CurrentUserContext) -> tuple[Agent, AuthorizationScope]:
        agent = self.authorization.require_visible(context, agent_id)
        return agent, self.authorization.require_action_for_visible(context, agent, PermissionKey.ACTIVITY_READ)

    def _status(
        self,
        agent: Agent,
        connection: SyncProviderConnection | None,
        folder: SyncAgentFolder | None,
        now: datetime,
    ) -> AgentFileSyncRead:
        plugin = self._file_sync_plugin(connection)
        if connection is None or plugin is None:
            return AgentFileSyncRead(
                enabled=agent.file_sync_enabled,
                state=AgentFileSyncState.NOT_CONNECTED,
                provider=None,
                folder_url=None,
                last_contact_at=None,
                retry_at=None,
            )
        last_contact_at = folder.last_contact_at if folder is not None else None
        retry_at = None
        if not agent.file_sync_enabled:
            state = AgentFileSyncState.TURNED_OFF
        elif folder is None or folder.folder_item_id is None or folder.status != SyncFolderStatus.ACTIVE:
            state = AgentFileSyncState.SETTING_UP
        elif connection.sync_retry_at is not None and connection.sync_retry_at > now:
            state = AgentFileSyncState.THROTTLED
            retry_at = connection.sync_retry_at
        elif last_contact_at is None:
            state = AgentFileSyncState.WAITING_FOR_RESTART
        elif agent.status in (AgentStatus.RUNNING, AgentStatus.ERROR) and now - last_contact_at > NOT_SYNCING_AFTER:
            state = AgentFileSyncState.NOT_SYNCING
        else:
            state = AgentFileSyncState.SYNCED
        return AgentFileSyncRead(
            enabled=agent.file_sync_enabled,
            state=state,
            provider=AgentFileSyncProviderRead(key=plugin.key, display_name=plugin.display_name),
            folder_url=folder.folder_web_url if folder is not None else None,
            last_contact_at=last_contact_at,
            retry_at=retry_at,
        )

    def _file_sync_plugin(self, connection: SyncProviderConnection | None) -> SyncProviderPlugin | None:
        if connection is None:
            return None
        try:
            plugin = self.plugins.require(connection.provider_key)
        except KeyError:
            return None
        return plugin if SyncProviderCapability.FILE_SYNC in plugin.capabilities else None

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
