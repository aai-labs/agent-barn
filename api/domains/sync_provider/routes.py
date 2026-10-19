from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.sync_provider.models import (
    SyncLocationChoice,
    SyncLocationRead,
    SyncProviderAuthorizeUrlRead,
    SyncProviderRead,
    SyncProviderSignInCreate,
)
from api.domains.sync_provider.service import SyncProviderPurpose, SyncProviderService

sync_provider_router = APIRouter(prefix="/organizations/{organization_id}/sync-providers", tags=["sync-providers"])

# Organization-independent: each provider's callback is the redirect URI registered with that provider.
sync_provider_callback_router = APIRouter(prefix="/integrations/sync-provider", tags=["sync-providers"])


@sync_provider_router.get("", response_model=list[SyncProviderRead])
def list_sync_providers(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SyncProviderService, Injected(SyncProviderService)],
):
    return service.providers(organization_id, context)


@sync_provider_router.get("/{provider_key}/connection/authorize-url", response_model=SyncProviderAuthorizeUrlRead)
def sync_provider_authorize_url(
    organization_id: UUID,
    provider_key: str,
    purpose: SyncProviderPurpose,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SyncProviderService, Injected(SyncProviderService)],
):
    return SyncProviderAuthorizeUrlRead(
        authorize_url=service.authorize_url(organization_id, provider_key, purpose, context)
    )


@sync_provider_router.delete("/{provider_key}/connection", status_code=status.HTTP_204_NO_CONTENT)
def abandon_sync_provider_connection(
    organization_id: UUID,
    provider_key: str,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SyncProviderService, Injected(SyncProviderService)],
):
    service.abandon_pending(organization_id, provider_key, context)


@sync_provider_router.post("/{provider_key}/connection/sign-in", response_model=SyncProviderRead)
def complete_sync_provider_sign_in(
    organization_id: UUID,
    provider_key: str,
    data: SyncProviderSignInCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SyncProviderService, Injected(SyncProviderService)],
):
    return service.complete_sign_in(organization_id, provider_key, data.code, data.state, context)


@sync_provider_router.post("/{provider_key}/connection/disconnect", response_model=SyncProviderRead)
def disconnect_sync_provider(
    organization_id: UUID,
    provider_key: str,
    data: SyncProviderSignInCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SyncProviderService, Injected(SyncProviderService)],
):
    return service.disconnect(organization_id, provider_key, data.code, data.state, context)


@sync_provider_router.get("/{provider_key}/connection/locations", response_model=list[SyncLocationRead])
def search_sync_provider_locations(
    organization_id: UUID,
    provider_key: str,
    search: str,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SyncProviderService, Injected(SyncProviderService)],
):
    return service.locations(organization_id, provider_key, search, context)


@sync_provider_router.post("/{provider_key}/connection/location", response_model=SyncProviderRead)
def choose_sync_provider_location(
    organization_id: UUID,
    provider_key: str,
    data: SyncLocationChoice,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SyncProviderService, Injected(SyncProviderService)],
):
    return service.choose_location(organization_id, provider_key, data.location_id, context)


@sync_provider_callback_router.get("/{provider_key}/callback", response_class=HTMLResponse)
def sync_provider_callback(
    provider_key: str,
    request: Request,
    service: Annotated[SyncProviderService, Injected(SyncProviderService)],
):
    return service.callback_page(provider_key, dict(request.query_params))
