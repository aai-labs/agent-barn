from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.ssh.models import (
    SshAssignmentsRead,
    SshAssignmentsUpdate,
    SshCredentialCreate,
    SshCredentialRead,
    SshCredentialUpdate,
)
from api.domains.ssh.service import SshService


class SafeSshRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={"detail": "Invalid SSH configuration fields"})

        return safe_handler


router = APIRouter(prefix="/organizations/{organization_id}", tags=["ssh"], route_class=SafeSshRoute)
Context = Annotated[CurrentUserContext, Depends(get_current_user())]
Service = Annotated[SshService, Injected(SshService)]


@router.get("/ssh-credentials")
def list_keys(
    context: Context,
    service: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 100,
    search: str = "",
) -> dict:
    return service.list_keys(context, page, page_size, search)


@router.post("/ssh-credentials", response_model=SshCredentialRead, status_code=201)
def create_key(data: SshCredentialCreate, context: Context, service: Service) -> SshCredentialRead:
    return service.create_key(data, context)


@router.get("/ssh-credentials/{key_id}", response_model=SshCredentialRead)
def get_key(key_id: UUID, context: Context, service: Service) -> SshCredentialRead:
    return service.get_key(key_id, context)


@router.put("/ssh-credentials/{key_id}", response_model=SshCredentialRead)
def update_key(key_id: UUID, data: SshCredentialUpdate, context: Context, service: Service) -> SshCredentialRead:
    return service.update_key(key_id, data, context)


@router.delete("/ssh-credentials/{key_id}", status_code=204)
def delete_key(key_id: UUID, context: Context, service: Service) -> None:
    service.delete_key(key_id, context)


@router.get("/agents/{agent_id}/ssh-credentials", response_model=SshAssignmentsRead)
def assignments(agent_id: UUID, context: Context, service: Service) -> SshAssignmentsRead:
    return service.assignments(agent_id, context)


@router.put("/agents/{agent_id}/ssh-credentials", response_model=SshAssignmentsRead)
def apply(agent_id: UUID, data: SshAssignmentsUpdate, context: Context, service: Service) -> SshAssignmentsRead:
    return service.apply(agent_id, data, context)
