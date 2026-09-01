from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from fastapi_injector import Injected

from api.domains.communications.delivery_repository import CommunicationDeliveryCancelledError
from api.domains.communications.gateway_service import CommunicationsGatewayService
from api.domains.communications.models import (
    AcceptedCommunicationRead,
    RuntimeDeliveryRead,
    RuntimeDeliveryResult,
    RuntimeReplyCreate,
)

SUPPORTED_RUNTIME_PROTOCOL_VERSIONS = frozenset({"1", "2"})

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
    if protocol_version != "2":
        raise HTTPException(
            status_code=status.HTTP_426_UPGRADE_REQUIRED,
            detail="The persistent runtime control stream requires Communications protocol version 2",
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
        delivery = service.claim_runtime_delivery(agent)
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


@provider_webhook_router.post("/{connection_id}", status_code=status.HTTP_202_ACCEPTED)
def accept_provider_webhook(
    connection_id: UUID,
    payload: dict[str, Any],
    service: Annotated[CommunicationsGatewayService, Injected(CommunicationsGatewayService)],
    authorization: Annotated[str, Header()],
) -> dict[str, list[AcceptedCommunicationRead]]:
    try:
        accepted = service.accept_provider_webhook(connection_id, payload, authorization)
    except (PermissionError, NotImplementedError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Webhook authentication failed") from exc
    return {"accepted": accepted}
