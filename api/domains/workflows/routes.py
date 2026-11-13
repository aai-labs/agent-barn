from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.workflows.models import (
    WorkflowArchive,
    WorkflowCapabilitiesRead,
    WorkflowCreate,
    WorkflowRead,
    WorkflowSummaryRead,
    WorkflowUpdate,
    WorkflowVersionCreate,
    WorkflowVersionRead,
)
from api.domains.workflows.service import WorkflowService
from api.infrastructure.shared.models import PaginatedItems

router = APIRouter(prefix="/organizations/{organization_id}", tags=["workflows"])
Context = Annotated[CurrentUserContext, Depends(get_current_user())]
Service = Annotated[WorkflowService, Injected(WorkflowService)]


@router.get("/workflow-capabilities", response_model=WorkflowCapabilitiesRead)
def get_workflow_capabilities(organization_id: UUID, context: Context, service: Service):
    return service.capabilities(organization_id, context)


@router.get("/workflows", response_model=PaginatedItems[WorkflowSummaryRead])
def list_workflows(
    organization_id: UUID,
    context: Context,
    service: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    created_by_me: bool = False,
    archived: bool | None = None,
):
    return service.list_workflows(
        organization_id, context, page, page_size, created_by_me=created_by_me, archived=archived
    )


@router.post("/workflows", response_model=WorkflowRead, status_code=201)
def create_workflow(organization_id: UUID, payload: WorkflowCreate, context: Context, service: Service):
    return service.create(organization_id, payload, context)


@router.get("/workflows/{workflow_id}", response_model=WorkflowRead)
def get_workflow(organization_id: UUID, workflow_id: UUID, context: Context, service: Service):
    return service.get(organization_id, workflow_id, context)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowRead)
def update_workflow(
    organization_id: UUID, workflow_id: UUID, payload: WorkflowUpdate, context: Context, service: Service
):
    return service.update(organization_id, workflow_id, payload, context)


@router.get("/workflows/{workflow_id}/versions", response_model=PaginatedItems[WorkflowVersionRead])
def list_workflow_versions(
    organization_id: UUID,
    workflow_id: UUID,
    context: Context,
    service: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return service.versions(organization_id, workflow_id, context, page, page_size)


@router.post("/workflows/{workflow_id}/versions", response_model=WorkflowRead, status_code=201)
def save_workflow_version(
    organization_id: UUID, workflow_id: UUID, payload: WorkflowVersionCreate, context: Context, service: Service
):
    return service.save(organization_id, workflow_id, payload, context)


@router.post("/workflows/{workflow_id}/archive", status_code=204)
def archive_workflow(
    organization_id: UUID, workflow_id: UUID, payload: WorkflowArchive, context: Context, service: Service
) -> Response:
    service.archive(organization_id, workflow_id, payload.expected_revision, context)
    return Response(status_code=204)
