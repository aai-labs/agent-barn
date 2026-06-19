from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi_injector import Injected

from api.domains.agents.models import (
    AgentCreate,
    AgentFilter,
    AgentHealthRead,
    AgentRead,
    AgentUpdate,
    PairRequest,
    get_agent_filter,
)
from api.domains.agents.service import AgentService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.templates.models import TemplateRead
from api.infrastructure.shared.models import PaginatedItems, Pagination

agents_router = APIRouter(prefix="/agents", tags=["agents"])


@agents_router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
def create_agent(
    data: AgentCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
):
    return service.create_agent(data, context)


@agents_router.get("", response_model=PaginatedItems[AgentRead])
def list_agents(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
    agent_filter: Annotated[AgentFilter, Depends(get_agent_filter)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1)] = 15,
):
    return service.list_agents(
        agent_filter=agent_filter,
        pagination=Pagination(page=page, size=page_size),
        context=context,
    )


@agents_router.get("/models")
def list_models(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
):
    return service.list_models(context)


@agents_router.get("/{agent_id}", response_model=AgentRead)
def get_agent(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
):
    return service.get_agent(agent_id, context)


@agents_router.get("/{agent_id}/template/{version}", response_model=TemplateRead)
def get_agent_template(
    agent_id: UUID,
    version: int,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
):
    return service.get_agent_template(agent_id, version, context)


@agents_router.patch("/{agent_id}", response_model=AgentRead)
def update_agent(
    agent_id: UUID,
    data: AgentUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
):
    return service.update_agent(agent_id, data, context)


@agents_router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
):
    service.delete_agent(agent_id, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@agents_router.post("/{agent_id}/start", response_model=AgentRead)
def start_agent(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
):
    return service.start_agent(agent_id, context)


@agents_router.post("/{agent_id}/stop", response_model=AgentRead)
def stop_agent(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
):
    return service.stop_agent(agent_id, context)


@agents_router.get("/{agent_id}/healthz", response_model=AgentHealthRead)
def get_agent_healthz(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
):
    return service.get_agent_health(agent_id, context)


@agents_router.post("/{agent_id}/pair")
def pair_agent(
    agent_id: UUID,
    data: PairRequest,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
):
    output = service.pair_agent(agent_id, data, context)
    return {"message": output}


@agents_router.get("/{agent_id}/slack/channels")
def list_slack_channels(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
    search: Annotated[str | None, Query()] = None,
):
    return service.list_slack_channels(agent_id, context, search=search)


@agents_router.get("/{agent_id}/slack/users")
def list_slack_users(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentService, Injected(AgentService)],
    search: Annotated[str | None, Query()] = None,
):
    return service.list_slack_users(agent_id, context, search=search)
