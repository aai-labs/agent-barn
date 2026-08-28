from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.communications.models import (
    CommunicationConnectionCreate,
    CommunicationConnectionRead,
    CommunicationConnectionUpdate,
    CommunicationDiagnosticsRead,
    CommunicationReconnectRead,
    CommunicationRetryRead,
    PlatformDescriptorRead,
)
from api.domains.communications.service import CommunicationsService

communications_router = APIRouter(
    prefix="/organizations/{organization_id}",
    tags=["communications"],
)


@communications_router.get("/communication-platforms", response_model=list[PlatformDescriptorRead])
def list_communication_platforms(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CommunicationsService, Injected(CommunicationsService)],
):
    return service.list_platforms(context)


@communications_router.get(
    "/agents/{agent_id}/connections",
    response_model=list[CommunicationConnectionRead],
)
def list_communication_connections(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CommunicationsService, Injected(CommunicationsService)],
):
    return service.list_connections(agent_id, context)


@communications_router.post(
    "/agents/{agent_id}/connections",
    response_model=CommunicationConnectionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_communication_connection(
    agent_id: UUID,
    data: CommunicationConnectionCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CommunicationsService, Injected(CommunicationsService)],
):
    return service.create_connection(agent_id, data, context)


@communications_router.get(
    "/agents/{agent_id}/connections/{connection_id}/app-package",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
)
def download_communication_app_package(
    agent_id: UUID,
    connection_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CommunicationsService, Injected(CommunicationsService)],
):
    filename, payload = service.build_app_package(agent_id, connection_id, context)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@communications_router.patch(
    "/agents/{agent_id}/connections/{connection_id}",
    response_model=CommunicationConnectionRead,
)
def update_communication_connection(
    agent_id: UUID,
    connection_id: UUID,
    data: CommunicationConnectionUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CommunicationsService, Injected(CommunicationsService)],
):
    return service.update_connection(agent_id, connection_id, data, context)


@communications_router.delete(
    "/agents/{agent_id}/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def retire_communication_connection(
    agent_id: UUID,
    connection_id: UUID,
    revision: Annotated[int, Query(ge=1)],
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CommunicationsService, Injected(CommunicationsService)],
) -> Response:
    service.retire_connection(agent_id, connection_id, revision, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@communications_router.get(
    "/agents/{agent_id}/connections/{connection_id}/diagnostics",
    response_model=CommunicationDiagnosticsRead,
)
def get_communication_connection_diagnostics(
    agent_id: UUID,
    connection_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CommunicationsService, Injected(CommunicationsService)],
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    window_minutes: Annotated[int | None, Query(ge=1, le=31 * 24 * 60)] = None,
):
    return service.get_diagnostics(
        agent_id,
        connection_id,
        context,
        since=since,
        until=until,
        window_minutes=window_minutes,
    )


@communications_router.post(
    "/agents/{agent_id}/connections/{connection_id}/reconnect",
    response_model=CommunicationReconnectRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def reconnect_communication_connection(
    agent_id: UUID,
    connection_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CommunicationsService, Injected(CommunicationsService)],
):
    return service.reconnect_connection(agent_id, connection_id, context)


@communications_router.post(
    "/agents/{agent_id}/connections/{connection_id}/deliveries/{delivery_id}/retry",
    response_model=CommunicationRetryRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_communication_delivery(
    agent_id: UUID,
    connection_id: UUID,
    delivery_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CommunicationsService, Injected(CommunicationsService)],
):
    return service.retry_delivery(agent_id, connection_id, delivery_id, context)
