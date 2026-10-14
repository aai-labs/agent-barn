from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.onedrive_sync.models import OneDriveSyncAuthorizeUrlRead, OneDriveSyncConnectionRead
from api.domains.onedrive_sync.service import OneDriveSyncPurpose, OneDriveSyncService

onedrive_sync_router = APIRouter(
    prefix="/organizations/{organization_id}/onedrive-sync/connection", tags=["onedrive-sync"]
)

# Fixed and organization-independent: it is the redirect URI registered on the platform app.
onedrive_sync_callback_router = APIRouter(prefix="/integrations/onedrive-sync", tags=["onedrive-sync"])


@onedrive_sync_router.get("", response_model=OneDriveSyncConnectionRead)
def onedrive_sync_status(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[OneDriveSyncService, Injected(OneDriveSyncService)],
):
    return service.status(organization_id, context)


@onedrive_sync_router.get("/authorize-url", response_model=OneDriveSyncAuthorizeUrlRead)
def onedrive_sync_authorize_url(
    organization_id: UUID,
    purpose: OneDriveSyncPurpose,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[OneDriveSyncService, Injected(OneDriveSyncService)],
):
    return OneDriveSyncAuthorizeUrlRead(authorize_url=service.authorize_url(organization_id, purpose, context))


@onedrive_sync_callback_router.get("/callback", response_class=HTMLResponse)
def onedrive_sync_callback(
    service: Annotated[OneDriveSyncService, Injected(OneDriveSyncService)],
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    admin_consent: str | None = Query(default=None),
):
    return service.callback_page(code, state, error, error_description, admin_consent)
