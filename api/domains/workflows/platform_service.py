from dataclasses import dataclass

from injector import inject, singleton

from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher
from api.domains.platform_admin.service import PlatformAdminService
from api.domains.workflows.platform_models import PlatformWorkflowSettingsRead, PlatformWorkflowSettingsUpdate
from api.domains.workflows.platform_repository import PlatformWorkflowRepository


@inject
@singleton
@dataclass
class PlatformWorkflowService:
    repository: PlatformWorkflowRepository
    authority: PlatformAdminService
    dispatcher: EventDeliveryDispatcher

    def read(self, context: CurrentUserContext) -> PlatformWorkflowSettingsRead:
        self.authority.require_platform_admin(context.user)
        return self.repository.read()

    def update(self, data: PlatformWorkflowSettingsUpdate, context: CurrentUserContext) -> PlatformWorkflowSettingsRead:
        self.authority.require_platform_admin(context.user)
        result, ids = self.repository.set_authoring(
            data.authoring_enabled,
            context.user.id,
            context.user.full_name or context.user.email,
        )
        self.dispatcher.enqueue_immediate(ids)
        return result
