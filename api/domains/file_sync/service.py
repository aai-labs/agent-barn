import secrets
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.models import Agent, AgentType
from api.domains.file_sync.models import FileSyncChangesCreate, SyncAgentFolder, SyncFolderStatus
from api.domains.file_sync.repository import FileSyncRepository
from api.domains.file_sync.rules import SyncCategory, classify
from api.domains.sync_provider.models import SyncProviderCapability, SyncProviderConnection
from api.domains.sync_provider.plugins.registry import SyncProviderPluginRegistry
from api.infrastructure.crypto import decrypt_token


class FileSyncUnauthorized(Exception):
    pass


class FileSyncNotFound(Exception):
    pass


class FileSyncConflict(Exception):
    pass


class FileSyncPathRefused(Exception):
    pass


@dataclass(frozen=True)
class FileSyncTarget:
    agent: Agent
    connection: SyncProviderConnection
    folder: SyncAgentFolder


@inject
@singleton
@dataclass
class FileSyncIngestService:
    repository: FileSyncRepository
    plugins: SyncProviderPluginRegistry
    config: Config

    def report_changes(self, agent_id: UUID, provided_key: str, changes: FileSyncChangesCreate) -> None:
        target = self._target(agent_id, provided_key)
        runtime = AgentType(target.agent.agent_type).value
        for entry in changes.entries:
            if (
                unicodedata.normalize("NFC", entry.path) != entry.path
                or classify(runtime, entry.path) == SyncCategory.NEVER
            ):
                raise FileSyncPathRefused(f"Path not synced: {entry.path!r}")

    def _target(self, agent_id: UUID, provided_key: str) -> FileSyncTarget:
        agent = self.repository.agent_including_deleted(agent_id)
        if agent is None or not agent.ingest_key_encrypted or not provided_key:
            raise FileSyncUnauthorized()
        stored_key = decrypt_token(agent.ingest_key_encrypted, self.config.agent_token_encryption_key)
        if not secrets.compare_digest(stored_key, provided_key):
            raise FileSyncUnauthorized()
        if agent.deleted_at is not None:
            raise FileSyncNotFound("Agent not found")
        connection, folder = self.repository.agent_sync_target(agent.organization_id, agent.id)
        if connection is None:
            raise FileSyncConflict("The Organization has no active sync connection")
        if SyncProviderCapability.FILE_SYNC not in self.plugins.require(connection.provider_key).capabilities:
            raise FileSyncConflict("The connected provider does not sync Agent files")
        if folder is None:
            raise FileSyncNotFound("The Agent's folder does not exist yet")
        if folder.status != SyncFolderStatus.ACTIVE:
            raise FileSyncConflict("File sync is turned off for this Agent")
        if folder.folder_item_id is None:
            raise FileSyncConflict("The Agent's folder is still being created")
        return FileSyncTarget(agent=agent, connection=connection, folder=folder)
