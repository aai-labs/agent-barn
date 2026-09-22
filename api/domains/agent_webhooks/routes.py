import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi_injector import Injected
from pydantic import ValidationError

from api.domains.agent_webhooks.models import (
    AgentWebhookCreate,
    AgentWebhookRead,
    AgentWebhookUpdate,
    WebhookDeliveryPlatformRead,
    WebhookInvocationAccepted,
    WebhookInvocationRead,
)
from api.domains.agent_webhooks.service import (
    SIGNATURE_HEADER,
    VERSION_HEADER,
    AgentWebhookService,
)
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.infrastructure.shared.models import PaginatedItems, Pagination

MAX_WEBHOOK_BODY_BYTES = 256 * 1024

agent_webhooks_router = APIRouter(
    prefix="/organizations/{organization_id}/agents/{agent_id}/webhooks",
    tags=["agent-webhooks"],
)
agent_webhook_ingress_router = APIRouter(prefix="/agent-hooks/v1", tags=["agent-webhook-ingress"])


@agent_webhooks_router.get("", response_model=list[AgentWebhookRead])
def list_agent_webhooks(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentWebhookService, Injected(AgentWebhookService)],
):
    return service.list_webhooks(agent_id, context)


@agent_webhooks_router.post("", response_model=AgentWebhookRead, status_code=status.HTTP_201_CREATED)
def create_agent_webhook(
    agent_id: UUID,
    payload: AgentWebhookCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentWebhookService, Injected(AgentWebhookService)],
):
    return service.create_webhook(agent_id, payload, context)


@agent_webhooks_router.get("/delivery-platforms", response_model=list[WebhookDeliveryPlatformRead])
def list_webhook_delivery_platforms(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentWebhookService, Injected(AgentWebhookService)],
):
    return service.list_delivery_platforms(agent_id, context)


@agent_webhooks_router.get("/{webhook_id}", response_model=AgentWebhookRead)
def get_agent_webhook(
    agent_id: UUID,
    webhook_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentWebhookService, Injected(AgentWebhookService)],
):
    return service.get_webhook(agent_id, webhook_id, context)


@agent_webhooks_router.patch("/{webhook_id}", response_model=AgentWebhookRead)
def update_agent_webhook(
    agent_id: UUID,
    webhook_id: UUID,
    payload: AgentWebhookUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentWebhookService, Injected(AgentWebhookService)],
):
    return service.update_webhook(agent_id, webhook_id, payload, context)


@agent_webhooks_router.post("/{webhook_id}/rotate-secret", response_model=AgentWebhookRead)
def rotate_agent_webhook_secret(
    agent_id: UUID,
    webhook_id: UUID,
    revision: Annotated[int, Query(ge=1)],
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentWebhookService, Injected(AgentWebhookService)],
):
    return service.rotate_secret(agent_id, webhook_id, revision, context)


@agent_webhooks_router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
def retire_agent_webhook(
    agent_id: UUID,
    webhook_id: UUID,
    revision: Annotated[int, Query(ge=1)],
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentWebhookService, Injected(AgentWebhookService)],
) -> Response:
    service.retire_webhook(agent_id, webhook_id, revision, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@agent_webhooks_router.get(
    "/{webhook_id}/invocations",
    response_model=PaginatedItems[WebhookInvocationRead],
)
def list_webhook_invocations(
    agent_id: UUID,
    webhook_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentWebhookService, Injected(AgentWebhookService)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return service.list_invocations(agent_id, webhook_id, context, Pagination(page=page, size=page_size))


@agent_webhooks_router.post(
    "/{webhook_id}/invocations/{invocation_id}/retry",
    response_model=WebhookInvocationRead,
)
def retry_webhook_invocation(
    agent_id: UUID,
    webhook_id: UUID,
    invocation_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentWebhookService, Injected(AgentWebhookService)],
):
    return service.retry_invocation(agent_id, webhook_id, invocation_id, context)


@agent_webhook_ingress_router.post(
    "/{webhook_id}",
    response_model=WebhookInvocationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def accept_webhook_invocation(
    webhook_id: UUID,
    request: Request,
    service: Annotated[AgentWebhookService, Injected(AgentWebhookService)],
    signature: Annotated[str, Header(alias=SIGNATURE_HEADER)] = "",
    version: Annotated[str, Header(alias=VERSION_HEADER)] = "",
):
    declared_length = request.headers.get("content-length", "")
    if declared_length.isdigit() and int(declared_length) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Webhook body is too large")
    raw_body = await request.body()
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Webhook body is too large")
    try:
        decoded = json.loads(raw_body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Webhook body is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Webhook body must be a JSON object")
    try:
        return service.accept_invocation(
            webhook_id,
            decoded,
            raw_body=raw_body,
            signature=signature,
            version=version,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Webhook authentication failed") from exc
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
