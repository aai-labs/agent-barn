"""Microsoft sign-in for SharePoint, on the agent's Teams app.

The popup flow mirrors ``google_oauth``: the UI fetches an authorize URL, Microsoft redirects
the popup to the unauthenticated callback, which posts the code and signed state back to the
opener, and the opener completes the sign-in through an authenticated request. See
``SharePointService`` for why it is a public client (PKCE, no secret).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from fastapi_injector import Injected
from pydantic import BaseModel

from api.domains.agents.sharepoint_service import SharePointService, SharePointSetupRead, SharePointSignInRead
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user

sharepoint_sign_in_router = APIRouter(
    prefix="/organizations/{organization_id}/agents/{agent_id}/integrations/sharepoint",
    tags=["integrations"],
)

# Fixed and organization-independent: it is the redirect URI customers register on their
# Teams app.
microsoft_callback_router = APIRouter(prefix="/integrations/microsoft", tags=["integrations"])


class SharePointAuthorizeUrlRead(BaseModel):
    authorize_url: str


class SharePointSignInComplete(BaseModel):
    code: str
    state: str


@sharepoint_sign_in_router.get("/setup", response_model=SharePointSetupRead)
def sharepoint_setup(
    agent_id: UUID,
    connection_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SharePointService, Injected(SharePointService)],
):
    return service.setup(agent_id, connection_id, context)


@sharepoint_sign_in_router.get("/authorize-url", response_model=SharePointAuthorizeUrlRead)
def sharepoint_authorize_url(
    agent_id: UUID,
    connection_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SharePointService, Injected(SharePointService)],
    read_only: bool = False,
):
    return SharePointAuthorizeUrlRead(authorize_url=service.authorize_url(agent_id, connection_id, read_only, context))


@sharepoint_sign_in_router.post("/sign-in", response_model=SharePointSignInRead)
def complete_sharepoint_sign_in(
    agent_id: UUID,
    data: SharePointSignInComplete,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SharePointService, Injected(SharePointService)],
):
    return service.complete_sign_in(agent_id, data.code, data.state, context)


@microsoft_callback_router.get("/callback", response_class=HTMLResponse)
def microsoft_callback(
    service: Annotated[SharePointService, Injected(SharePointService)],
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    admin_consent: str | None = Query(default=None),
):
    return service.callback_page(code, state, error, error_description, admin_consent)
