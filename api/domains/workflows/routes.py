from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.workflows.models import (
    WorkflowArchive,
    WorkflowCapabilitiesRead,
    WorkflowDraft,
    WorkflowRead,
    WorkflowSummaryRead,
    WorkflowVersionCreate,
    WorkflowVersionRead,
)
from api.domains.workflows.service import WorkflowService
from api.infrastructure.shared.models import PaginatedItems

router = APIRouter(prefix="/organizations/{organization_id}/agents/{agent_id}", tags=["workflows"])
Context = Annotated[CurrentUserContext, Depends(get_current_user())]
Service = Annotated[WorkflowService, Injected(WorkflowService)]


@router.get("/workflow-capabilities", response_model=WorkflowCapabilitiesRead)
def get_workflow_capabilities(agent_id: UUID, context: Context, service: Service):
    return service.capabilities(agent_id, context)


@router.get("/workflows", response_model=PaginatedItems[WorkflowSummaryRead])
def list_workflows(
    agent_id: UUID,
    context: Context,
    service: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return service.list_workflows(agent_id, context, page, page_size)


@router.post("/workflows", response_model=WorkflowRead, status_code=201)
def create_workflow(agent_id: UUID, payload: WorkflowDraft, context: Context, service: Service):
    return service.create(agent_id, payload, context)


@router.get("/workflows/{workflow_id}", response_model=WorkflowRead)
def get_workflow(agent_id: UUID, workflow_id: UUID, context: Context, service: Service):
    return service.get(agent_id, workflow_id, context)


@router.get("/workflows/{workflow_id}/versions", response_model=PaginatedItems[WorkflowVersionRead])
def list_workflow_versions(
    agent_id: UUID,
    workflow_id: UUID,
    context: Context,
    service: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return service.versions(agent_id, workflow_id, context, page, page_size)


@router.post("/workflows/{workflow_id}/versions", response_model=WorkflowRead, status_code=201)
def save_workflow_version(
    agent_id: UUID, workflow_id: UUID, payload: WorkflowVersionCreate, context: Context, service: Service
):
    return service.save(agent_id, workflow_id, payload, context)


@router.post("/workflows/{workflow_id}/archive", status_code=204)
def archive_workflow(
    agent_id: UUID, workflow_id: UUID, payload: WorkflowArchive, context: Context, service: Service
) -> Response:
    service.archive(agent_id, workflow_id, payload.expected_revision, context)
    return Response(status_code=204)
