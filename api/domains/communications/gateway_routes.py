import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from fastapi_injector import Injected
from starlette.concurrency import run_in_threadpool

from api.domains.communications.agent_message_service import AgentMessageService
from api.domains.communications.delivery_repository import CommunicationDeliveryCancelledError
from api.domains.communications.gateway_service import CommunicationsGatewayService
from api.domains.communications.models import (
    AcceptedCommunicationRead,
    AgentMessageCreate,
    AgentMessageRead,
    RuntimeDeliveryRead,
    RuntimeDeliveryResult,
    RuntimeReplyCreate,
)
from api.domains.communications.plugins.base import WebhookRequest

# 3 added the delivery execution contract (kind, server-owned session key, event
# policy). Older versions stay accepted: a pod runs the adapter it was given when it
# started, so it keeps speaking its own version until the Agent is restarted.
SUPPORTED_RUNTIME_PROTOCOL_VERSIONS = frozenset({"1", "2", "3"})
_CONTROL_STREAM_PROTOCOL_VERSIONS = frozenset({"2", "3"})

runtime_communications_router = APIRouter(prefix="/agents", tags=["runtime-communications"])
driver_communications_router = APIRouter(prefix="/connections", tags=["platform-driver-communications"])
provider_webhook_router = APIRouter(prefix="/webhooks", tags=["provider-webhooks"])


def _authenticate(
    service: CommunicationsGatewayService,
    agent_id: UUID,
    authorization: str,
    protocol_version: str,
):
    if protocol_version not in SUPPORTED_RUNTIME_PROTOCOL_VERSIONS:
        raise HTTPException(
            status_code=status.HTTP_426_UPGRADE_REQUIRED,
            detail=f"Unsupported Communications protocol version: {protocol_version}",
        )
    provided_key = authorization.removeprefix("Bearer ").strip()
    try:
        return service.authenticate_runtime(agent_id, provided_key)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from exc


@runtime_communications_router.get("/{agent_id}/control")
def stream_runtime_control(
    agent_id: UUID,
    service: Annotated[CommunicationsGatewayService, Injected(CommunicationsGatewayService)],
    authorization: Annotated[str, Header()],
    protocol_version: Annotated[str, Header(alias="X-AgentBarn-Communications-Version")],
) -> StreamingResponse:
    if protocol_version not in _CONTROL_STREAM_PROTOCOL_VERSIONS:
        raise HTTPException(
            status_code=status.HTTP_426_UPGRADE_REQUIRED,
            detail="The persistent runtime control stream requires Communications protocol version 2 or later",
        )
    agent = _authenticate(service, agent_id, authorization, protocol_version)
    return StreamingResponse(
        service.stream_runtime_control(agent),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@runtime_communications_router.post(
    "/{agent_id}/deliveries/claim",
    response_model=RuntimeDeliveryRead,
    responses={204: {"description": "No pending delivery"}},
)
def claim_runtime_delivery(
    agent_id: UUID,
    service: Annotated[CommunicationsGatewayService, Injected(CommunicationsGatewayService)],
    authorization: Annotated[str, Header()],
    protocol_version: Annotated[str, Header(alias="X-AgentBarn-Communications-Version")],
):
    agent = _authenticate(service, agent_id, authorization, protocol_version)
    try:
        delivery = service.claim_runtime_delivery(agent, runtime_protocol_version=int(protocol_version))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if delivery is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return delivery


@runtime_communications_router.post(
    "/{agent_id}/deliveries/{delivery_id}/complete",
    status_code=status.HTTP_204_NO_CONTENT,
)
def complete_runtime_delivery(
    agent_id: UUID,
    delivery_id: UUID,
    result: RuntimeDeliveryResult,
    service: Annotated[CommunicationsGatewayService, Injected(CommunicationsGatewayService)],
    authorization: Annotated[str, Header()],
    protocol_version: Annotated[str, Header(alias="X-AgentBarn-Communications-Version")],
) -> Response:
    agent = _authenticate(service, agent_id, authorization, protocol_version)
    if not service.complete_runtime_delivery(agent, delivery_id, result):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Communication Delivery not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@runtime_communications_router.post(
    "/{agent_id}/deliveries/{delivery_id}/release",
    status_code=status.HTTP_204_NO_CONTENT,
)
def release_runtime_delivery(
    agent_id: UUID,
    delivery_id: UUID,
    service: Annotated[CommunicationsGatewayService, Injected(CommunicationsGatewayService)],
    authorization: Annotated[str, Header()],
    protocol_version: Annotated[str, Header(alias="X-AgentBarn-Communications-Version")],
) -> Response:
    """Return a claimed delivery to the queue because the Agent could not start it.

    Distinct from complete: nothing ran, so nothing should be reported as done and the
    attempt spent claiming it is given back.
    """
    agent = _authenticate(service, agent_id, authorization, protocol_version)
    if not service.release_runtime_delivery(agent, delivery_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Communication Delivery not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@runtime_communications_router.post(
    "/{agent_id}/deliveries/{delivery_id}/renew",
    status_code=status.HTTP_204_NO_CONTENT,
)
def renew_runtime_delivery_lease(
    agent_id: UUID,
    delivery_id: UUID,
    service: Annotated[CommunicationsGatewayService, Injected(CommunicationsGatewayService)],
    authorization: Annotated[str, Header()],
    protocol_version: Annotated[str, Header(alias="X-AgentBarn-Communications-Version")],
    awaiting_input: bool = False,
) -> Response:
    agent = _authenticate(service, agent_id, authorization, protocol_version)
    try:
        renewed = service.renew_runtime_delivery_lease(agent, delivery_id, awaiting_input=awaiting_input)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not renewed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Communication Delivery not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@runtime_communications_router.post(
    "/{agent_id}/deliveries/{delivery_id}/replies",
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_runtime_reply(
    agent_id: UUID,
    delivery_id: UUID,
    reply: RuntimeReplyCreate,
    service: Annotated[CommunicationsGatewayService, Injected(CommunicationsGatewayService)],
    authorization: Annotated[str, Header()],
    protocol_version: Annotated[str, Header(alias="X-AgentBarn-Communications-Version")],
) -> dict[str, UUID]:
    agent = _authenticate(service, agent_id, authorization, protocol_version)
    try:
        outbound_delivery_id = service.enqueue_runtime_reply(agent, delivery_id, reply)
    except CommunicationDeliveryCancelledError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"delivery_id": outbound_delivery_id}


@driver_communications_router.post("/{connection_id}/events", status_code=status.HTTP_202_ACCEPTED)
def accept_driver_event(
    connection_id: UUID,
    payload: dict[str, Any],
    service: Annotated[CommunicationsGatewayService, Injected(CommunicationsGatewayService)],
    authorization: Annotated[str, Header()],
    protocol_version: Annotated[str, Header(alias="X-AgentBarn-Driver-Version")],
) -> dict[str, list[AcceptedCommunicationRead]]:
    if protocol_version != "1":
        raise HTTPException(status_code=status.HTTP_426_UPGRADE_REQUIRED, detail="Unsupported Platform Driver version")
    try:
        accepted = service.accept_driver_event(
            connection_id,
            authorization.removeprefix("Bearer ").strip(),
            payload,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from exc
    return {"accepted": accepted}


@provider_webhook_router.post("/email/inbound", status_code=status.HTTP_202_ACCEPTED)
def accept_email_inbound(
    payload: dict[str, Any],
    service: Annotated[CommunicationsGatewayService, Injected(CommunicationsGatewayService)],
    authorization: Annotated[str, Header()],
) -> dict[str, list[AcceptedCommunicationRead]]:
    try:
        accepted = service.accept_email_inbound(payload, authorization)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Webhook authentication failed") from exc
    return {"accepted": accepted}


# This endpoint is reachable by anyone who learns a Connection id, and nothing is
# authenticated until the plugin has seen the body. Cap what we are willing to read.
MAX_WEBHOOK_BODY_BYTES = 256 * 1024


@provider_webhook_router.post("/{connection_id}", status_code=status.HTTP_202_ACCEPTED)
async def accept_provider_webhook(
    connection_id: UUID,
    request: Request,
    service: Annotated[CommunicationsGatewayService, Injected(CommunicationsGatewayService)],
    # Optional because not every scheme uses it: a signature-based caller authenticates
    # with a header of its own and sends no Authorization at all. Requiring one here
    # would reject those callers with a 422 before any plugin saw the request.
    authorization: Annotated[str, Header()] = "",
) -> dict[str, list[AcceptedCommunicationRead]]:
    # The body is read raw rather than declared as a parsed dict: an HMAC signature is
    # over the bytes that were sent, and re-serializing a parsed dict does not reproduce
    # them. Parsing here is what lets a plugin verify before anyone trusts the content.
    raw_body = await request.body()
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Webhook body is too large",
        )
    try:
        payload = json.loads(raw_body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Webhook body is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Webhook body must be a JSON object")

    webhook_request = WebhookRequest(
        raw_body=raw_body,
        payload=payload,
        authorization=authorization,
        headers=dict(request.headers),
    )
    try:
        # The service does blocking database and decryption work. Sync endpoints get a
        # threadpool from FastAPI automatically; this one is async for the raw body, so
        # it hands that work off explicitly rather than stalling the event loop.
        accepted = await run_in_threadpool(service.accept_provider_webhook, connection_id, webhook_request)
    except (PermissionError, NotImplementedError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Webhook authentication failed") from exc
    except ValueError as exc:
        # The caller is who they claim to be, but the request itself is unusable --
        # an unsupported contract version, a missing required field.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"accepted": accepted}


@runtime_communications_router.post("/{agent_id}/messages", status_code=status.HTTP_202_ACCEPTED)
def submit_agent_message(
    agent_id: UUID,
    request: AgentMessageCreate,
    service: Annotated[CommunicationsGatewayService, Injected(CommunicationsGatewayService)],
    messages: Annotated[AgentMessageService, Injected(AgentMessageService)],
    authorization: Annotated[str, Header()],
    protocol_version: Annotated[str, Header(alias="X-AgentBarn-Communications-Version")],
) -> AgentMessageRead:
    agent = _authenticate(service, agent_id, authorization, protocol_version)
    return messages.submit_agent_message(agent, request)
