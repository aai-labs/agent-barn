from dataclasses import dataclass

from injector import inject, singleton

from api.core.config import Config
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher
from api.domains.organizations.models import OrganizationSettingsRead, OrganizationSettingsUpdate
from api.domains.organizations.settings_repository import OrganizationSettingsRepository
from api.domains.platform_admin.service import PlatformAdminService


@inject
@singleton
@dataclass
class OrganizationSettingsService:
    """The platform's settings for every Organization. Its own service, depending on
    nothing but its repository and platform authority, so Agents can read the default
    Agent limit without pulling in the rest of Organizations."""

    repository: OrganizationSettingsRepository
    authority: PlatformAdminService
    config: Config
    dispatcher: EventDeliveryDispatcher

    def default_agent_limit(self) -> int:
        """How many Agents an Organization that is not a trial may run, unless it has its
        own limit: the platform's setting, else the deployment's default."""
        return self.repository.read(self.config.organization_default_agent_limit).default_agent_limit

    def read(self, context: CurrentUserContext) -> OrganizationSettingsRead:
        self.authority.require_platform_admin(context.user)
        return self.repository.read(self.config.organization_default_agent_limit)

    def update(self, data: OrganizationSettingsUpdate, context: CurrentUserContext) -> OrganizationSettingsRead:
        self.authority.require_platform_admin(context.user)
        stored, delivery_ids = self.repository.set_settings(
            data.model_dump(include=data.model_fields_set),
            self.config.organization_default_agent_limit,
            context.user.id,
            context.user.full_name or context.user.email,
        )
        self.dispatcher.enqueue_immediate(delivery_ids)
        return stored
