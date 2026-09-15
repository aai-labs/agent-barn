from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.restore_points.models import AgentRestorePointCreate, AgentRestorePointRead
from api.domains.restore_points.service import RestorePointService
from api.infrastructure.shared.models import PaginatedItems, Pagination

restore_points_router = APIRouter(prefix="/organizations/{organization_id}/agents", tags=["restore-points"])


@restore_points_router.post(
    "/{agent_id}/restore-points",
    response_model=AgentRestorePointRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_restore_point(
    agent_id: UUID,
    payload: AgentRestorePointCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[RestorePointService, Injected(RestorePointService)],
):
    return service.create_restore_point(agent_id, payload, context)


@restore_points_router.get("/{agent_id}/restore-points", response_model=PaginatedItems[AgentRestorePointRead])
def list_restore_points(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[RestorePointService, Injected(RestorePointService)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1)] = 15,
):
    return service.list_restore_points(agent_id, context, Pagination(page=page, size=page_size))


@restore_points_router.post(
    "/{agent_id}/restore-points/{restore_point_id}/restore",
    response_model=AgentRestorePointRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def restore_restore_point(
    agent_id: UUID,
    restore_point_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[RestorePointService, Injected(RestorePointService)],
):
    return service.restore_restore_point(agent_id, restore_point_id, context)


@restore_points_router.delete(
    "/{agent_id}/restore-points/{restore_point_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_restore_point(
    agent_id: UUID,
    restore_point_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[RestorePointService, Injected(RestorePointService)],
) -> None:
    service.delete_restore_point(agent_id, restore_point_id, context)


@restore_points_router.get(
    "/{agent_id}/restore-points/{restore_point_id}",
    response_model=AgentRestorePointRead,
)
def get_restore_point(
    agent_id: UUID,
    restore_point_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[RestorePointService, Injected(RestorePointService)],
):
    return service.get_restore_point(agent_id, restore_point_id, context)
