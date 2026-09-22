import json
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, HTTPException, Response, status
from fastapi_injector import Injected

from api.core.config import Config
from api.domains.communications.gateway_service import CommunicationsGatewayService
from api.domains.communications.models import AcceptedCommunicationRead
from api.domains.communications.teams_runtime_webhook import (
    RuntimeWebhookUnavailable,
    TeamsRuntimeWebhookRelay,
)
from api.infrastructure.http import resilient_request

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
    config: Annotated[Config, Injected(Config)],
    # Optional: a signature-based caller (e.g. the webhook plugin) sends no
    # Authorization header at all. Required-vs-optional is only enforced here;
    # the fallback proxy below still forwards whatever value it got.
    authorization: Annotated[str, Header()] = "",
) -> Response:
    """Keep the public URL stable while runtime-owned Teams bypasses Communications."""
    try:
        result = relay.relay(connection_id, payload, authorization)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Webhook authentication failed") from exc
    except RuntimeWebhookUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if result is not None:
        headers = {"Content-Type": result.content_type} if result.content_type else None
        return Response(content=result.body, status_code=result.status_code, headers=headers)

    # Empty/runtime-disabled Teams remains a safe rollback: only this fallback
    # depends on the Communications deployment, while runtime-owned Teams does not.
    try:
        response = resilient_request(
            "POST",
            f"{config.communications_base_url.rstrip('/')}/webhooks/{connection_id}",
            headers={"Authorization": authorization, "Content-Type": "application/json"},
            content=json.dumps(payload, separators=(",", ":")).encode(),
            timeout=10,
            max_retries=0,
            label="Gateway-owned provider webhook proxy",
        )
    except httpx.TransportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Communications Gateway webhook is unavailable",
        ) from exc
    headers = {"Content-Type": response.headers["Content-Type"]} if "Content-Type" in response.headers else None
    return Response(content=response.content, status_code=response.status_code, headers=headers)
