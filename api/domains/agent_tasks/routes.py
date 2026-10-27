"""The Task routes people use to read an Agent's Tasks and download their Files."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi_injector import Injected

from api.domains.agent_tasks.models import AgentTaskDetail, AgentTaskFilter, AgentTaskRead, AgentTaskStatus
from api.domains.agent_tasks.service import AgentTaskService
from api.domains.artifacts.models import ArtifactLinkRead
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.infrastructure.shared.models import PaginatedItems, Pagination

agent_tasks_router = APIRouter(prefix="/organizations/{organization_id}/agents/{agent_id}/tasks", tags=["agent-tasks"])
tasks_router = APIRouter(prefix="/organizations/{organization_id}/tasks", tags=["agent-tasks"])


@agent_tasks_router.get("", response_model=PaginatedItems[AgentTaskRead])
def list_agent_tasks(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentTaskService, Injected(AgentTaskService)],
    task_status: Annotated[AgentTaskStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return service.list_agent_tasks(
        agent_id, context, AgentTaskFilter(status=task_status), Pagination(page=page, size=page_size)
    )


@agent_tasks_router.get("/{task_id}", response_model=AgentTaskDetail)
def get_agent_task(
    agent_id: UUID,
    task_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentTaskService, Injected(AgentTaskService)],
):
    return service.get_task(agent_id, task_id, context)


@agent_tasks_router.get("/{task_id}/files/{file_id}/download-link", response_model=ArtifactLinkRead)
def task_file_download_link(
    agent_id: UUID,
    task_id: UUID,
    file_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentTaskService, Injected(AgentTaskService)],
):
    """A short-lived link to the File's Artifact; the Artifacts download route serves its bytes."""
    return service.file_link(agent_id, task_id, file_id, context)


@tasks_router.get("", response_model=PaginatedItems[AgentTaskRead])
def list_tasks(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentTaskService, Injected(AgentTaskService)],
    agent_id: Annotated[UUID | None, Query()] = None,
    task_status: Annotated[AgentTaskStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return service.list_organization_tasks(
        context, AgentTaskFilter(agent_id=agent_id, status=task_status), Pagination(page=page, size=page_size)
    )
