from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError

from api.domains.agent_sizes.models import (
    AgentSize,
    AgentSizeCreate,
    AgentSizeRead,
    AgentSizeUpdate,
    check_requests_within_limits,
)
from api.domains.agent_sizes.repository import Actor, AgentSizeRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher


def to_read(size: AgentSize) -> AgentSizeRead:
    return AgentSizeRead.model_validate(size, from_attributes=True)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent size not found")


@inject
@singleton
@dataclass
class AgentSizeService:
    """The Agent Size catalog, kept by Platform Administrators.

    Authorization is the route's `require_platform_admin`: the catalog is a Platform
    Resource with no Organization-scoped equivalent. The rules that keep the catalog usable
    live here: exactly one default, the default always enabled, unique names, and requests
    that never exceed limits.
    """

    repository: AgentSizeRepository
    event_delivery_dispatcher: EventDeliveryDispatcher

    def list_sizes(self) -> list[AgentSizeRead]:
        return [to_read(size) for size in self.repository.list_all()]

    def create_size(self, data: AgentSizeCreate, context: CurrentUserContext) -> AgentSizeRead:
        if self.repository.name_taken(data.name):
            raise _conflict(f"A size named {data.name!r} already exists")
        size = AgentSize(**data.model_dump(), is_default=False)
        try:
            result = self.repository.create_with_event(size, actor=_actor(context))
        except IntegrityError:
            raise _conflict(f"A size named {data.name!r} already exists") from None
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        return to_read(result.size)

    def update_size(self, size_id: UUID, data: AgentSizeUpdate, context: CurrentUserContext) -> AgentSizeRead:
        changes = data.model_dump(exclude_unset=True)
        if any(value is None for value in changes.values()):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Fields cannot be null")
        size = self.repository.get(size_id)
        if size is None:
            raise _not_found()

        merged = {**size.model_dump(), **changes}
        try:
            check_requests_within_limits(
                merged["cpu_request_millicores"],
                merged["cpu_limit_millicores"],
                merged["memory_request_bytes"],
                merged["memory_limit_bytes"],
            )
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
        if "name" in changes and self.repository.name_taken(changes["name"], excluding=size_id):
            raise _conflict(f"A size named {changes['name']!r} already exists")
        if size.is_default and merged["enabled"] is False:
            raise _conflict("The default size can't be disabled. Make another size the default first.")
        if changes.get("is_default") and not merged["enabled"]:
            raise _conflict("Enable the size before making it the default.")

        try:
            result = self.repository.update_with_events(size_id, changes, actor=_actor(context))
        except IntegrityError:
            # Another administrator's save got there first: a clashing name, or a default
            # that changed underneath this one.
            raise _conflict("The catalog changed while saving. Reload and try again.") from None
        if result is None:
            raise _not_found()
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        return to_read(result.size)

    def delete_size(self, size_id: UUID, context: CurrentUserContext) -> None:
        size = self.repository.get(size_id)
        if size is None:
            raise _not_found()
        if size.is_default:
            raise _conflict("The default size can't be deleted. Make another size the default first.")
        if self.repository.is_referenced(size_id):
            raise _conflict("Agents are on this size. Disable it instead, so it can't be chosen again.")
        result = self.repository.delete_with_event(size_id, actor=_actor(context))
        if result is None:
            raise _not_found()
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)


def _actor(context: CurrentUserContext) -> Actor:
    return Actor(user_id=context.user.id, display=context.user.full_name or context.user.email)
