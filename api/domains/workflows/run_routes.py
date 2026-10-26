from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi_injector import Injected

from api.domains.workflows.routes import Context
from api.domains.workflows.run_models import (
    WorkflowHistoryRead,
    WorkflowRunCancel,
    WorkflowRunCreate,
    WorkflowRunRead,
    WorkflowRunRerun,
)
from api.domains.workflows.run_service import WorkflowRunService
from api.infrastructure.shared.models import PaginatedItems

router = APIRouter(prefix="/organizations/{organization_id}/agents/{agent_id}", tags=["workflows"])
Service = Annotated[WorkflowRunService, Injected(WorkflowRunService)]
Page = Annotated[int, Query(ge=1)]
Size = Annotated[int, Query(ge=1, le=100)]


@router.post("/workflows/{workflow_id}/runs", status_code=202, response_model=WorkflowRunRead)
def start_run(agent_id: UUID, workflow_id: UUID, payload: WorkflowRunCreate, context: Context, service: Service):
    return service.start(agent_id, workflow_id, payload, context)


@router.post("/workflow-runs/{run_id}/re-run", status_code=202, response_model=WorkflowRunRead)
def rerun_run(agent_id: UUID, run_id: UUID, payload: WorkflowRunRerun, context: Context, service: Service):
    return service.rerun(agent_id, run_id, payload, context)


@router.get("/workflow-runs", response_model=PaginatedItems[WorkflowRunRead])
def list_runs(
    agent_id: UUID,
    context: Context,
    service: Service,
    page: Page = 1,
    page_size: Size = 20,
    workflow_id: UUID | None = None,
):
    return service.list_runs(agent_id, context, page, page_size, workflow_id)


@router.get("/workflow-runs/{run_id}", response_model=WorkflowRunRead)
def get_run(agent_id: UUID, run_id: UUID, context: Context, service: Service):
    return service.get(agent_id, run_id, context)


@router.post("/workflow-runs/{run_id}/cancel", response_model=WorkflowRunRead)
def cancel_run(agent_id: UUID, run_id: UUID, payload: WorkflowRunCancel, context: Context, service: Service):
    return service.cancel(agent_id, run_id, payload.expected_revision, context)


@router.get("/workflow-runs/{run_id}/history", response_model=PaginatedItems[WorkflowHistoryRead])
def history(agent_id: UUID, run_id: UUID, context: Context, service: Service, page: Page = 1, page_size: Size = 20):
    return service.history(agent_id, run_id, context, page, page_size)
