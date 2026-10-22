from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi_injector import Injected

from api.domains.agent_sizes.models import AgentSizeChoice
from api.domains.agents.models import PlatformAgentRead
from api.domains.agents.platform_service import PlatformAgentService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin
from api.infrastructure.shared.models import PaginatedItems

# Platform Oversight surface: no Active Organization is resolved, and the organization
# filter narrows the list rather than naming a scope the caller belongs to.
platform_agents_router = APIRouter(prefix="/platform/agents", tags=["platform-agents"])


@platform_agents_router.get("", response_model=PaginatedItems[PlatformAgentRead])
def list_platform_agents(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformAgentService, Injected(PlatformAgentService)],
    organization_id: Annotated[UUID | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
):
    """Every live Agent, ordered by Organization name, then Agent name."""
    return service.list_agents(organization_id=organization_id, search=search, page=page, page_size=page_size)


@platform_agents_router.put("/{agent_id}/agent-size", response_model=PlatformAgentRead)
def set_platform_agent_size(
    agent_id: UUID,
    choice: AgentSizeChoice,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformAgentService, Injected(PlatformAgentService)],
):
    """Override one Agent's size, locking it for its Organization, or null to clear the override.

    The Agent is not restarted: it starts on the size next time, and `pending_size` says so
    until then.
    """
    return service.set_agent_size(agent_id, choice.agent_size_id, context)
