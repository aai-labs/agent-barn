from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agent_sizes.lookup import AgentSizeCatalog, AgentSizeLookupService, to_option
from api.domains.agent_sizes.models import size_is_pending
from api.domains.agents.models import PlatformAgentRead, PlatformAgentRow
from api.domains.agents.repository import AgentRepository, AgentSizeVanished
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.infrastructure.shared.models import PaginatedItems, Pagination


def _not_found(agent_id: UUID) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found")


def _size_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Only an enabled size in the catalog can be set.",
    )


@inject
@singleton
@dataclass
class PlatformAgentService:
    """Every Agent on the platform, and a Platform Administrator's override of one's size.

    Authorization is the routes' `require_platform_admin`; no Membership is checked. Reads
    are Platform Oversight Data (identity, lifecycle, size). The size override is the one
    write a Platform Administrator makes on an Organization's Agent, and it is deliberately
    narrow: it never starts, stops or reconfigures the Agent, which picks the size up at its
    next start. See docs/adr/2026-10-22-platform-administrators-set-an-agents-size.md.
    """

    repository: AgentRepository
    agent_sizes: AgentSizeLookupService
    event_delivery_dispatcher: EventDeliveryDispatcher

    def list_agents(
        self,
        *,
        organization_id: UUID | None,
        search: str | None,
        page: int,
        page_size: int,
    ) -> PaginatedItems[PlatformAgentRead]:
        rows, total = self.repository.find_platform_agents(
            organization_id=organization_id,
            search=search.strip() if search else None,
            pagination=Pagination(page=page, size=page_size),
        )
        catalog = self.agent_sizes.catalog()
        return PaginatedItems(
            page=page,
            page_size=page_size,
            total=total,
            items=[_to_read(row, catalog) for row in rows],
        )

    def set_agent_size(
        self, agent_id: UUID, agent_size_id: UUID | None, context: CurrentUserContext
    ) -> PlatformAgentRead:
        """Give one Agent a size, or None to clear the override.

        Any enabled size in the catalog, whether or not the Agent's Organization may choose
        it. Setting one locks the size for the Organization; clearing puts the Agent back on
        the default and unlocks it. Holds the Agent's lifecycle lock, as the Organization's
        own choice does, so it cannot interleave with a start or stop.
        """
        row = self.repository.get_platform_agent(agent_id)
        if row is None:
            raise _not_found(agent_id)
        unchanged = row.agent_size_id == agent_size_id and row.agent_size_set_by_platform == (agent_size_id is not None)
        if unchanged:
            # Before the size rules, so re-sending a size since disabled is the no-op it is.
            return _to_read(row, self.agent_sizes.catalog())
        if agent_size_id is not None:
            size = self.agent_sizes.catalog().sizes.get(agent_size_id)
            if size is None or not size.enabled:
                raise _size_unavailable()

        agent = self.repository.get_by_id(agent_id)
        if agent is None:
            raise _not_found(agent_id)
        with self.repository.lifecycle_lock(agent.id) as acquired:
            if not acquired:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Agent {agent.id} has a lifecycle operation already in progress",
                )
            try:
                result = self.repository.set_agent_size_with_event(
                    agent,
                    agent_size_id,
                    actor=resolve_actor_identity(context, agent.organization_id),
                    actor_display=context.user.full_name or context.user.email,
                    by_platform=True,
                )
            except AgentSizeVanished:
                raise _size_unavailable() from None
        if result is None:
            # Deleted between the read and the write.
            raise _not_found(agent_id)
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        updated = self.repository.get_platform_agent(agent_id)
        if updated is None:
            raise _not_found(agent_id)
        return _to_read(updated, self.agent_sizes.catalog())


def _to_read(row: PlatformAgentRow, catalog: AgentSizeCatalog) -> PlatformAgentRead:
    size = catalog.resolve(row.agent_size_id)
    return PlatformAgentRead(
        id=row.id,
        name=row.name,
        status=row.status,
        agent_type=row.agent_type,
        created_at=row.created_at,
        organization_id=row.organization_id,
        organization_name=row.organization_name,
        agent_size_id=row.agent_size_id,
        agent_size=to_option(size),
        agent_size_set_by_platform=row.agent_size_set_by_platform,
        pending_size=size_is_pending(row.running_resources, size),
    )
