import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response, status
from fastapi_injector import Injected

from api.domains.ingest.models import IngestBatchRequest
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
