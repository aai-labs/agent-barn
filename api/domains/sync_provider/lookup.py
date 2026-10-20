from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.sync_provider.models import SyncProviderStatus
from api.domains.sync_provider.plugins.base import SyncLocationGuard
from api.domains.sync_provider.plugins.registry import SyncProviderPluginRegistry
from api.domains.sync_provider.repository import SyncProviderRepository


@inject
@singleton
@dataclass
class SyncProviderLookupService:
    """Read-only sync connection resolution for other domains' services."""

    repository: SyncProviderRepository
    plugins: SyncProviderPluginRegistry

    def sharepoint_folder_site_id(self, organization_id: UUID) -> str | None:
        """The SharePoint site holding the Organization's folder: the active connection's location,
        when its provider keeps Agents' SharePoint grants off that site."""
        for connection in self.repository.list_open(organization_id):
            if connection.status != SyncProviderStatus.ACTIVE:
                continue
            try:
                plugin = self.plugins.require(connection.provider_key)
            except KeyError:
                continue
            if plugin.location_guard == SyncLocationGuard.SHAREPOINT_AGENT_SITES:
                return connection.location_id
        return None
