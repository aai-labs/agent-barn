import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi_injector import Injected

from api.domains.agents.models import Agent
from api.domains.agents.sharepoint_service import SharePointAccessTokenRead, SharePointService
from api.domains.ingest.models import IngestBatchRequest, IngestCommunicationEventBatch
from api.domains.ingest.service import IngestService, authenticated_agent

logger = logging.getLogger(__name__)

ingest_router = APIRouter(prefix="/agents", tags=["ingest"])


@ingest_router.post("/{agent_id}/events", status_code=status.HTTP_204_NO_CONTENT)
def ingest_events(
    agent: Annotated[Agent, Depends(authenticated_agent)],
    batch: IngestBatchRequest,
    service: Annotated[IngestService, Injected(IngestService)],
):
    service.process(agent, batch)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@ingest_router.post("/{agent_id}/communication-events", status_code=status.HTTP_204_NO_CONTENT)
def ingest_communication_events(
    agent: Annotated[Agent, Depends(authenticated_agent)],
    batch: IngestCommunicationEventBatch,
    service: Annotated[IngestService, Injected(IngestService)],
):
    service.record_communication_events(agent, batch)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@ingest_router.post("/{agent_id}/integrations/sharepoint/token", response_model=SharePointAccessTokenRead)
def sharepoint_access_token(
    agent: Annotated[Agent, Depends(authenticated_agent)],
    sharepoint: Annotated[SharePointService, Injected(SharePointService)],
):
    """A short-lived app-only Microsoft token for an agent limited to selected SharePoint sites.

    Served here because the ingest app is where Agents authenticate with their ingest key;
    the main API authenticates people. The Teams app's secret that mints the token stays in the API.
    """
    return sharepoint.access_token(agent.id)
