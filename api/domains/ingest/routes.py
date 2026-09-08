import logging
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response, status
from fastapi_injector import Injected

from api.core.config import get_config
from api.domains.costs.usage_service import HonchoUsageService
from api.domains.ingest.models import IngestBatchRequest
from api.domains.ingest.service import IngestService

logger = logging.getLogger(__name__)

ingest_router = APIRouter(prefix="/agents", tags=["ingest"])
honcho_router = APIRouter(prefix="/honcho", tags=["ingest"])


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


@honcho_router.post("/usage", status_code=status.HTTP_204_NO_CONTENT)
def ingest_honcho_usage(
    payload: list[dict] | dict,
    service: Annotated[HonchoUsageService, Injected(HonchoUsageService)],
    authorization: Annotated[str, Header()],
):
    """Accept a CloudEvents batch from Honcho's telemetry emitter.

    Honcho posts these on its own schedule with no Agent context, so this is
    authenticated by a shared key rather than an Agent ingest key.
    """
    config = get_config()
    provided_key = authorization.removeprefix("Bearer ").strip()
    if not config.honcho_telemetry_key or not secrets.compare_digest(config.honcho_telemetry_key, provided_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    service.record_cloud_events(payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
