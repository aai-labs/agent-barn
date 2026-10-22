"""The Agent's own Task routes, served by the ingest app and authenticated by the Agent's ingest key.

The Agent and its Organization always come from the key, never from the request.
"""

from collections.abc import AsyncIterator, Iterator
from typing import Annotated
from uuid import UUID

from anyio import from_thread
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi_injector import Injected
from pydantic import ValidationError

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


def _file_metadata(filename: Annotated[str, Query()], content_type: Annotated[str, Header()]) -> AgentTaskFileCreate:
    try:
        return AgentTaskFileCreate(filename=filename, content_type=content_type)
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from None


def _blocking_pieces(body: AsyncIterator[bytes]) -> Iterator[bytes]:
    """The request body as the worker thread's plain iterator, read one piece at a time."""
    while (piece := from_thread.run(anext, body, None)) is not None:
        if piece:
            yield piece


async def _drain(body: AsyncIterator[bytes], max_bytes: int) -> None:
    """Read and drop what is left of a refused upload, so the client gets the refusal rather than a reset.

    Bounded, so a client that keeps sending only gets its connection closed.
    """
    total = 0
    async for piece in body:
        total += len(piece)
        if total > max_bytes:
            return


@agent_task_router.post(
    "/{agent_id}/tasks/{task_id}/files", response_model=AgentTaskFileRead, status_code=status.HTTP_201_CREATED
)
async def attach_file(
    agent: Annotated[Agent, Depends(authenticated_agent)],
    task_id: UUID,
    metadata: Annotated[AgentTaskFileCreate, Depends(_file_metadata)],
    request: Request,
    service: Annotated[AgentTaskService, Injected(AgentTaskService)],
):
    """Store the raw request body as a Task File, streamed: it is never held whole."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit():
        service.refuse_oversized_file(int(declared))
    body = request.stream()
    try:
        return await run_in_threadpool(
            service.attach_file, agent.organization_id, agent.id, task_id, metadata, _blocking_pieces(body)
        )
    except HTTPException:
        await _drain(body, service.file_max_bytes)
        raise


@agent_task_router.delete("/{agent_id}/tasks/{task_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_file(
    agent: Annotated[Agent, Depends(authenticated_agent)],
    task_id: UUID,
    file_id: UUID,
    service: Annotated[AgentTaskService, Injected(AgentTaskService)],
):
    service.remove_file(agent.organization_id, agent.id, task_id, file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
