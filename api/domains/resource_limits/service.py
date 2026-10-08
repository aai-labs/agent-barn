from dataclasses import dataclass

from injector import inject, singleton

from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher
from api.domains.resource_limits.models import PlatformResourceLimits, ResourceLimitsRead, ResourceLimitsUpdate
from api.domains.resource_limits.repository import ResourceLimitsRepository


def _read(limits: PlatformResourceLimits | None) -> ResourceLimitsRead:
    if limits is None:
        return ResourceLimitsRead()
    return ResourceLimitsRead(
        limits_memory_bytes=limits.limits_memory_bytes,
        limits_cpu_cores=limits.limits_cpu_cores,
        requests_memory_bytes=limits.requests_memory_bytes,
        requests_cpu_cores=limits.requests_cpu_cores,
        updated_at=limits.updated_at,
    )


@inject
@singleton
@dataclass
class ResourceLimitsService:
    """The capacity limits a Platform Administrator has entered.

    Authorization is the route's `require_platform_admin`: a Platform Administrator has no
    Membership to check, and there is no Organization-scoped equivalent of these limits.
    """

    repository: ResourceLimitsRepository
    event_delivery_dispatcher: EventDeliveryDispatcher

    def get_limits(self) -> ResourceLimitsRead:
        return _read(self.repository.get())

    def update_limits(self, data: ResourceLimitsUpdate, context: CurrentUserContext) -> ResourceLimitsRead:
        changes = data.model_dump(exclude_unset=True)
        if not changes:
            return self.get_limits()
        result = self.repository.set_with_events(
            changes,
            actor_user_id=context.user.id,
            actor_display=context.user.full_name or context.user.email,
        )
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        return _read(result.limits)
