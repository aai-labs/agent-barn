from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi_injector import Injected

from api.domains.workflows.routes import Context
from api.domains.workflows.run_models import (
    ApprovalDecisionCreate,
    WorkflowHistoryRead,
    WorkflowRunCancel,
    WorkflowRunCreate,
    WorkflowRunRead,
    WorkflowRunRerun,
)
from api.domains.workflows.run_service import WorkflowRunService
from api.infrastructure.shared.models import PaginatedItems


def _organization(organization_id: UUID) -> None:
    """Declares the path's Organization, which the request context authorizes, in the API description."""


# Runs are addressed by their own id; the Agent that runs one is data on the run, not part of its address.
router = APIRouter(
    prefix="/organizations/{organization_id}/workflow-runs", tags=["workflows"], dependencies=[Depends(_organization)]
)
Service = Annotated[WorkflowRunService, Injected(WorkflowRunService)]
Page = Annotated[int, Query(ge=1)]
Size = Annotated[int, Query(ge=1, le=100)]


@router.post("", status_code=202, response_model=WorkflowRunRead)
def start_run(payload: WorkflowRunCreate, context: Context, service: Service):
    return service.start(payload, context)


@router.get("", response_model=PaginatedItems[WorkflowRunRead])
def list_runs(
    context: Context,
    service: Service,
    page: Page = 1,
    page_size: Size = 20,
    workflow_id: UUID | None = None,
    agent_id: UUID | None = None,
    awaiting_decision: bool = False,
    status: Literal["active", "settled"] | None = None,
):
    return service.list_runs(context, page, page_size, workflow_id, agent_id, awaiting_decision, status)


@router.get("/{run_id}", response_model=WorkflowRunRead)
def get_run(run_id: UUID, context: Context, service: Service):
    return service.get(run_id, context)


@router.post("/{run_id}/re-run", status_code=202, response_model=WorkflowRunRead)
def rerun_run(run_id: UUID, payload: WorkflowRunRerun, context: Context, service: Service):
    return service.rerun(run_id, payload, context)


@router.post("/{run_id}/cancel", response_model=WorkflowRunRead)
def cancel_run(run_id: UUID, payload: WorkflowRunCancel, context: Context, service: Service):
    return service.cancel(run_id, payload.expected_revision, context)


@router.post("/{run_id}/approvals/{request_id}/decision", response_model=WorkflowRunRead)
def decide_approval(
    run_id: UUID, request_id: UUID, payload: ApprovalDecisionCreate, context: Context, service: Service
):
    return service.decide(run_id, request_id, payload, context)


@router.get("/{run_id}/history", response_model=PaginatedItems[WorkflowHistoryRead])
def history(
    run_id: UUID,
    context: Context,
    service: Service,
    page: Page = 1,
    page_size: Size = 20,
    newest_first: bool = False,
):
    return service.history(run_id, context, page, page_size, newest_first)
