from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError

from api.domains.agent_sizes.lookup import AgentSizeLookupService, to_option
from api.domains.agent_sizes.models import (
    AgentSize,
    AgentSizeCreate,
    AgentSizeRead,
    AgentSizeUpdate,
    OrganizationAgentSizesRead,
    check_requests_within_limits,
)
from api.domains.agent_sizes.repository import Actor, AgentSizeInUse, AgentSizeRepository, AgentSizesNotAllowable
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.organizations.models import PlatformOrganizationRead
from api.domains.organizations.repository import OrganizationRepository
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy


def to_read(size: AgentSize, agent_counts: Mapping[UUID | None, int]) -> AgentSizeRead:
    return AgentSizeRead.model_validate(size, from_attributes=True).model_copy(
        update={
            "agent_count": agent_counts.get(size.id, 0),
            "following_agent_count": agent_counts.get(None, 0) if size.is_default else 0,
        }
    )


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent spec not found")


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

    def list_sizes(self, organization_id: UUID | None = None) -> list[AgentSizeRead]:
        """The catalog, with how many live Agents each size holds, in one Organization when given."""
        agent_counts = self.repository.agent_counts(organization_id)
        return [to_read(size, agent_counts) for size in self.repository.list_all()]

    def create_size(self, data: AgentSizeCreate, context: CurrentUserContext) -> AgentSizeRead:
        if self.repository.name_taken(data.name):
            raise _conflict(f"A spec named {data.name!r} already exists")
        size = AgentSize(**data.model_dump(), is_default=False)
        try:
            result = self.repository.create_with_event(size, actor=_actor(context))
        except IntegrityError:
            raise _conflict(f"A spec named {data.name!r} already exists") from None
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        return to_read(result.size, {})

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
            raise _conflict(f"A spec named {changes['name']!r} already exists")
        if size.is_default and merged["enabled"] is False:
            raise _conflict("The default spec can't be disabled. Make another spec the default first.")
        if changes.get("is_default") and not merged["enabled"]:
            raise _conflict("Enable the spec before making it the default.")

        try:
            result = self.repository.update_with_events(size_id, changes, actor=_actor(context))
        except IntegrityError:
            # Another administrator's save got there first: a clashing name, or a default
            # that changed underneath this one.
            raise _conflict("The catalog changed while saving. Reload and try again.") from None
        if result is None:
            raise _not_found()
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        return to_read(result.size, self.repository.agent_counts())

    def delete_size(self, size_id: UUID, context: CurrentUserContext) -> None:
        size = self.repository.get(size_id)
        if size is None:
            raise _not_found()
        if size.is_default:
            raise _conflict("The default spec can't be deleted. Make another spec the default first.")
        try:
            result = self.repository.delete_with_event(size_id, actor=_actor(context))
        except AgentSizeInUse:
            raise _conflict("Agents are on this spec. Disable it instead, so it can't be chosen again.") from None
        if result is None:
            raise _not_found()
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)


@inject
@singleton
@dataclass
class OrganizationAgentSizeService:
    """Which sizes an Organization's Agents may be put on.

    The platform decides the allowed set; any member may read what it can choose, so the
    hire form and the Agent page can offer it. Choosing a size for an Agent is the Agents
    domain's, under agent.size.manage.
    """

    repository: AgentSizeRepository
    lookup: AgentSizeLookupService
    organization_repository: OrganizationRepository
    permission_policy: PermissionPolicy
    event_delivery_dispatcher: EventDeliveryDispatcher

    def get_choosable(self, organization_id: UUID, context: CurrentUserContext) -> OrganizationAgentSizesRead:
        self.permission_policy.require_organization(
            context,
            organization_id,
            PermissionKey.ORGANIZATION_READ,
            detail="You don't have permission for this organization.",
        )
        sizes = self.lookup.choosable(organization_id)
        return OrganizationAgentSizesRead(can_choose=len(sizes) > 1, sizes=[to_option(size) for size in sizes])

    def set_allowed(
        self, organization_id: UUID, size_ids: list[UUID], context: CurrentUserContext
    ) -> PlatformOrganizationRead:
        """Replace the sizes an Organization may choose beyond the default.

        Platform-administered, like the spend ceiling: a bigger size spends shared cluster
        capacity, so an Organization cannot grant itself one. Withdrawing a size leaves
        the Agents already on it where they are; it only stops it being chosen again.
        """
        try:
            delivery_ids = self.repository.set_allowed_with_event(
                organization_id,
                set(size_ids),
                actor=resolve_actor_identity(context, organization_id),
                actor_display=context.user.full_name or context.user.email,
            )
        except AgentSizesNotAllowable:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only enabled specs in the catalog can be allowed.",
            ) from None
        if delivery_ids is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization {organization_id} not found"
            )
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
        organization = self.organization_repository.get_platform_read(organization_id)
        if organization is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization {organization_id} not found"
            )
        return organization


def _actor(context: CurrentUserContext) -> Actor:
    return Actor(user_id=context.user.id, display=context.user.full_name or context.user.email)
