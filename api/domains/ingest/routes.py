import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response, status
from fastapi_injector import Injected

from api.domains.agents.sharepoint_service import SharePointAccessTokenRead, SharePointService
from api.domains.ingest.models import IngestBatchRequest, IngestCommunicationEventBatch
from api.domains.ingest.service import IngestService

logger = logging.getLogger(__name__)

ingest_router = APIRouter(prefix="/agents", tags=["ingest"])


@ingest_router.post("/{agent_id}/events", status_code=status.HTTP_204_NO_CONTENT)
def ingest_events(
    agent_id: UUID,
    batch: IngestBatchRequest,
    service: Annotated[IngestService, Injected(IngestService)],
    authorization: Annotated[str, Header()],
):
    provided_key = authorization.removeprefix("Bearer ").strip()
    try:
        agent = service.authenticate(agent_id, provided_key)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    service.process(agent, batch)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@ingest_router.post("/{agent_id}/communication-events", status_code=status.HTTP_204_NO_CONTENT)
def ingest_communication_events(
    agent_id: UUID,
    batch: IngestCommunicationEventBatch,
    service: Annotated[IngestService, Injected(IngestService)],
    authorization: Annotated[str, Header()],
):
    provided_key = authorization.removeprefix("Bearer ").strip()
    try:
        agent = service.authenticate(agent_id, provided_key)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    service.record_communication_events(agent, batch)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@ingest_router.post("/{agent_id}/integrations/sharepoint/token", response_model=SharePointAccessTokenRead)
def sharepoint_access_token(
    agent_id: UUID,
    service: Annotated[IngestService, Injected(IngestService)],
    sharepoint: Annotated[SharePointService, Injected(SharePointService)],
    authorization: Annotated[str, Header()],
):
    """A short-lived app-only Microsoft token for an agent limited to selected SharePoint sites.

    Served here because pods can only reach the ingest app, which already authenticates each
    agent by its ingest key. The Teams app's secret that mints the token stays in the API.
    """
    provided_key = authorization.removeprefix("Bearer ").strip()
    try:
        service.authenticate(agent_id, provided_key)
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    return sharepoint.access_token(agent_id)
