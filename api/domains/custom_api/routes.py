from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.custom_api.models import (
    CustomApiConnectionApply,
    CustomApiConnectionCreate,
    CustomApiConnectionRead,
    CustomApiConnectionsApply,
    CustomApiConnectionUpdate,
)
from api.domains.custom_api.service import CustomApiService


class CredentialSafeRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={"detail": "Invalid Custom API connection fields"})

        return safe_handler


custom_api_router = APIRouter(
    route_class=CredentialSafeRoute,
    prefix="/organizations/{organization_id}/agents/{agent_id}/custom-api-connections",
    tags=["custom-api-connections"],
)


@custom_api_router.get("", response_model=list[CustomApiConnectionRead])
def list_connections(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CustomApiService, Injected(CustomApiService)],
):
    return service.list_connections(agent_id, context)


@custom_api_router.post("", response_model=CustomApiConnectionRead, status_code=201)
def create_connection(
    agent_id: UUID,
    data: CustomApiConnectionCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CustomApiService, Injected(CustomApiService)],
):
    return service.create(agent_id, data, context)


@custom_api_router.patch("/{connection_id}", response_model=CustomApiConnectionRead)
def update_connection(
    agent_id: UUID,
    connection_id: UUID,
    data: CustomApiConnectionUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CustomApiService, Injected(CustomApiService)],
):
    return service.update(agent_id, connection_id, data, context)


@custom_api_router.post("/apply", response_model=list[CustomApiConnectionRead])
def apply_connections(
    agent_id: UUID,
    data: CustomApiConnectionsApply,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CustomApiService, Injected(CustomApiService)],
):
    return service.apply_many(agent_id, data, context)


@custom_api_router.post("/preflight", status_code=204)
def preflight_connections(
    agent_id: UUID,
    data: CustomApiConnectionsApply,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CustomApiService, Injected(CustomApiService)],
):
    service.apply_many(agent_id, data, context, preflight=True)


@custom_api_router.delete("/{connection_id}", status_code=204)
def delete_connection(
    agent_id: UUID,
    connection_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CustomApiService, Injected(CustomApiService)],
    restart: bool = False,
):
    service.delete(agent_id, connection_id, context, restart)


@custom_api_router.post("/{connection_id}/apply", response_model=CustomApiConnectionRead)
def apply_connection(
    agent_id: UUID,
    connection_id: UUID,
    data: CustomApiConnectionApply,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CustomApiService, Injected(CustomApiService)],
):
    return service.apply(agent_id, connection_id, data, context)
