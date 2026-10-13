from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response, status
from fastapi_injector import Injected

from api.domains.communications.gateway_service import CommunicationsGatewayService
from api.domains.communications.models import AcceptedCommunicationRead
from api.domains.communications.teams_runtime_webhook import (
    RuntimeWebhookUnavailable,
    TeamsRuntimeWebhookRelay,
)

runtime_provider_webhook_router = APIRouter(prefix="/communications/v1/webhooks", tags=["provider-webhooks"])


@runtime_provider_webhook_router.post("/email/inbound", status_code=status.HTTP_202_ACCEPTED)
def accept_email_inbound_at_api_edge(
    payload: dict[str, Any],
    service: Annotated[CommunicationsGatewayService, Injected(CommunicationsGatewayService)],
    authorization: Annotated[str, Header()],
) -> dict[str, list[AcceptedCommunicationRead]]:
    """Accept mailbox-addressed email at the API edge without a gateway hop."""
    try:
        accepted = service.accept_email_inbound(payload, authorization)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Webhook authentication failed") from exc
    return {"accepted": accepted}


@runtime_provider_webhook_router.post("/{connection_id}", response_model=None)
def accept_provider_webhook_at_api_edge(
    connection_id: UUID,
    payload: dict[str, Any],
    relay: Annotated[TeamsRuntimeWebhookRelay, Injected(TeamsRuntimeWebhookRelay)],
    authorization: Annotated[str, Header()],
) -> Response:
    """Keep the public URL stable while runtime-owned Teams bypasses Communications."""
    try:
        result = relay.relay(connection_id, payload, authorization)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Webhook authentication failed") from exc
    except RuntimeWebhookUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    headers = {"Content-Type": result.content_type} if result.content_type else None
    return Response(content=result.body, status_code=result.status_code, headers=headers)
