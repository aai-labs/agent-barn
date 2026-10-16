from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.sync_provider.models import SyncProviderStatus
from api.domains.sync_provider.repository import SyncProviderRepository


@inject
@singleton
@dataclass
class SyncProviderLookupService:
    """Read-only sync connection resolution for other domains' services.

    Imports nothing but the repository, so the SharePoint integration can ask which site
    holds the Organization's folder without an import cycle.
    """

    repository: SyncProviderRepository

    def folder_location_id(self, organization_id: UUID, provider_key: str) -> str | None:
        connection = self.repository.get_open(organization_id, provider_key)
        if connection is None or connection.status != SyncProviderStatus.ACTIVE:
            return None
        return connection.location_id
