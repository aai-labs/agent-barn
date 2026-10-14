from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.onedrive_sync.models import OneDriveSyncStatus
from api.domains.onedrive_sync.repository import OneDriveSyncRepository


@inject
@singleton
@dataclass
class OneDriveSyncLookupService:
    """Read-only OneDrive sync resolution for other domains' services.

    Imports nothing but the repository, so the SharePoint integration can ask which site
    holds the Organization's folder without an import cycle.
    """

    repository: OneDriveSyncRepository

    def folder_site_id(self, organization_id: UUID) -> str | None:
        connection = self.repository.get_open(organization_id)
        if connection is None or connection.status != OneDriveSyncStatus.ACTIVE:
            return None
        return connection.site_id
