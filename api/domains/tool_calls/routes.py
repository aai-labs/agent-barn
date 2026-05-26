from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi_injector import Injected

from api.domains.agents.service import AgentService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.tool_calls.models import (
    ToolCallFilter,
    ToolCallRead,
    get_tool_call_filter,
)
from api.domains.tool_calls.service import ToolCallService
from api.infrastructure.shared.models import PaginatedItems, Pagination

tool_calls_router = APIRouter(prefix="/agents", tags=["tool-calls"])


@tool_calls_router.get(
    "/{agent_id}/tool-calls", response_model=PaginatedItems[ToolCallRead]
)
def list_tool_calls(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    agent_service: Annotated[AgentService, Injected(AgentService)],
    tool_call_service: Annotated[ToolCallService, Injected(ToolCallService)],
    tool_call_filter: Annotated[ToolCallFilter, Depends(get_tool_call_filter)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1)] = 50,
):
    org_id = context.require_current_user_organization().organization_id
    agent_service.get_agent(agent_id, context)  # raises 404 if not found or wrong org
    return tool_call_service.list_tool_calls(
        agent_id, org_id, tool_call_filter, Pagination(page=page, size=page_size)
    )
