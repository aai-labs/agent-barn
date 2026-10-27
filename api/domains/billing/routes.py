from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user, require_platform_admin
from api.domains.billing.models import (
    BillingSettingsRead,
    BillingSettingsUpdate,
    CheckoutCreate,
    CheckoutRead,
    OrganizationBillingRead,
    PlatformCreditRecordRead,
)
from api.domains.billing.service import BillingService
from api.infrastructure.shared.models import PaginatedItems

# Stripe's events are a few kilobytes; anything far larger isn't one.
MAX_STRIPE_EVENT_BYTES = 256 * 1024

billing_router = APIRouter(prefix="/organizations/{organization_id}/billing", tags=["billing"])
platform_billing_settings_router = APIRouter(prefix="/platform/settings/billing", tags=["platform-settings"])
platform_billing_router = APIRouter(prefix="/platform/billing", tags=["platform-billing"])
stripe_webhook_router = APIRouter(prefix="/billing/stripe", tags=["billing"])


@billing_router.get("", response_model=OrganizationBillingRead)
def read_billing(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[BillingService, Injected(BillingService)],
):
    """The Organization's credit, what it has spent, and every change to its credit."""
    return service.get_billing(organization_id, context)


@billing_router.post("/checkout", response_model=CheckoutRead)
async def create_checkout(
    organization_id: UUID,
    data: CheckoutCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[BillingService, Injected(BillingService)],
):
    """Start buying credit: returns the payment page to send the Owner to."""
    return await service.create_checkout(organization_id, data, context)


@platform_billing_settings_router.get("", response_model=BillingSettingsRead)
def read_billing_settings(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[BillingService, Injected(BillingService)],
):
    return service.read_settings(context)


@platform_billing_settings_router.put("", response_model=BillingSettingsRead)
def update_billing_settings(
    data: BillingSettingsUpdate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[BillingService, Injected(BillingService)],
):
    return service.update_settings(data, context)


@platform_billing_router.get("/credit-history", response_model=PaginatedItems[PlatformCreditRecordRead])
def read_credit_history(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[BillingService, Injected(BillingService)],
    kind: Literal["trial", "purchase", "refund", "chargeback", "adjustment"] | None = None,
    organization_id: UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
):
    """Every Organization's purchases, refunds, chargebacks, adjustments and trial credit."""
    return service.list_credit_history(
        context, page=page, page_size=page_size, kind=kind, organization_id=organization_id
    )


@stripe_webhook_router.post("/webhook", status_code=status.HTTP_200_OK)
async def receive_stripe_event(
    request: Request,
    service: Annotated[BillingService, Injected(BillingService)],
    signature: Annotated[str, Header(alias="Stripe-Signature")] = "",
) -> dict[str, bool]:
    """Stripe's signed events. Unauthenticated by design: the signature is the proof."""
    declared_length = request.headers.get("content-length", "")
    if declared_length.isdigit() and int(declared_length) > MAX_STRIPE_EVENT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Event is too large")
    # Read a chunk at a time: a request sent without a length must not be buffered whole
    # before it can be refused.
    received = bytearray()
    async for chunk in request.stream():
        received.extend(chunk)
        if len(received) > MAX_STRIPE_EVENT_BYTES:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Event is too large")
    payload = bytes(received)
    try:
        await service.handle_webhook(payload, signature)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Signature verification failed") from exc
    return {"received": True}
