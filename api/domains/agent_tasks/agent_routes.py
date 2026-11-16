"""The Agent's own Task routes, served by the ingest app and authenticated by the Agent's ingest key.

The Agent and its Organization always come from the key, never from the request.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi_injector import Injected

from api.domains.agent_tasks.models import (
    AgentTaskCreate,
    AgentTaskDetail,
    AgentTaskFileCreate,
    AgentTaskFileRead,
    AgentTaskNoteCreate,
    AgentTaskNoteRead,
    AgentTaskRead,
    AgentTaskStatus,
    AgentTaskStatusUpdate,
)
from api.domains.agent_tasks.service import AgentTaskService
from api.domains.agents.models import Agent
from api.domains.ingest.service import authenticated_agent
from api.infrastructure.shared.models import PaginatedItems, Pagination

agent_task_router = APIRouter(prefix="/agents", tags=["agent-tasks"])


@agent_task_router.post("/{agent_id}/tasks", response_model=AgentTaskRead, status_code=status.HTTP_201_CREATED)
def create_task(
    agent: Annotated[Agent, Depends(authenticated_agent)],
    data: AgentTaskCreate,
    service: Annotated[AgentTaskService, Injected(AgentTaskService)],
):
    return service.create_task(agent.organization_id, agent.id, data)


@agent_task_router.get("/{agent_id}/tasks", response_model=PaginatedItems[AgentTaskRead])
def list_tasks(
    agent: Annotated[Agent, Depends(authenticated_agent)],
    service: Annotated[AgentTaskService, Injected(AgentTaskService)],
    task_status: Annotated[AgentTaskStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return service.list_own_tasks(agent.organization_id, agent.id, task_status, Pagination(page=page, size=page_size))


@agent_task_router.get("/{agent_id}/tasks/{task_id}", response_model=AgentTaskDetail)
def get_task(
    agent: Annotated[Agent, Depends(authenticated_agent)],
    task_id: UUID,
    service: Annotated[AgentTaskService, Injected(AgentTaskService)],
):
    return service.get_own_task(agent.organization_id, agent.id, task_id)


@agent_task_router.patch("/{agent_id}/tasks/{task_id}", response_model=AgentTaskRead)
def update_task_status(
    agent: Annotated[Agent, Depends(authenticated_agent)],
    task_id: UUID,
    data: AgentTaskStatusUpdate,
    service: Annotated[AgentTaskService, Injected(AgentTaskService)],
):
    return service.update_status(agent.organization_id, agent.id, task_id, data.status)


@agent_task_router.post(
    "/{agent_id}/tasks/{task_id}/notes", response_model=AgentTaskNoteRead, status_code=status.HTTP_201_CREATED
)
def add_note(
    agent: Annotated[Agent, Depends(authenticated_agent)],
    task_id: UUID,
    data: AgentTaskNoteCreate,
    service: Annotated[AgentTaskService, Injected(AgentTaskService)],
):
    return service.add_note(agent.organization_id, agent.id, task_id, data)


@agent_task_router.post(
    "/{agent_id}/tasks/{task_id}/files", response_model=AgentTaskFileRead, status_code=status.HTTP_201_CREATED
)
def attach_file(
    agent: Annotated[Agent, Depends(authenticated_agent)],
    task_id: UUID,
    data: AgentTaskFileCreate,
    service: Annotated[AgentTaskService, Injected(AgentTaskService)],
):
    """Attach an Artifact the Agent has published; the bytes went to Artifact storage, not here."""
    return service.attach_file(agent.organization_id, agent.id, task_id, data)


@agent_task_router.delete("/{agent_id}/tasks/{task_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_file(
    agent: Annotated[Agent, Depends(authenticated_agent)],
    task_id: UUID,
    file_id: UUID,
    service: Annotated[AgentTaskService, Injected(AgentTaskService)],
):
    service.remove_file(agent.organization_id, agent.id, task_id, file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
