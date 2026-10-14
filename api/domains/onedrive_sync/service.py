import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import jwt
from fastapi import HTTPException, status
from fastapi.responses import HTMLResponse, Response
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.microsoft_graph_scopes import (
    GRAPH_SCOPE_PREFIX,
    READ_PERMISSION,
    SITE_GRANT_PERMISSION,
    granted_permissions,
)
from api.domains.agents.microsoft_graph_sites import (
    MicrosoftGraphSites,
    SiteAccessRefused,
    SiteNotFound,
    SitesThrottled,
    SitesUnavailable,
)
from api.domains.agents.microsoft_identity import (
    MicrosoftIdentityClient,
    MicrosoftIdentityError,
    MicrosoftIdentityUnavailable,
    MicrosoftTokens,
    build_app_permission_consent_url,
    build_authorize_url,
    claims_from_id_token,
    pkce_pair,
)
from api.domains.agents.sharepoint_service import SharePointService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.service import JWT_ENCODING_ALGORITHM
from api.domains.onedrive_sync.models import (
    OneDriveSyncConnection,
    OneDriveSyncConnectionRead,
    OneDriveSyncSiteRead,
    OneDriveSyncStatus,
)
from api.domains.onedrive_sync.repository import OneDriveSyncConnectionConflict, OneDriveSyncRepository
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.crypto import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

MESSAGE_TYPE = "onedrive-sync-oauth"
MULTI_TENANT_AUTHORITY = "organizations"
SIGN_IN_SCOPES: tuple[str, ...] = tuple(
    sorted(
        {
            f"{GRAPH_SCOPE_PREFIX}{SITE_GRANT_PERMISSION}",
            f"{GRAPH_SCOPE_PREFIX}{READ_PERMISSION}",
            "openid",
            "profile",
        }
    )
)

_STATE_TYPE = "onedrive_sync_state"
_STATE_TTL_SECONDS = 600
_ADMIN_APPROVAL_ERROR_CODES = ("AADSTS65001", "AADSTS65004", "AADSTS90094", "AADSTS90095")

_NOT_CONFIGURED = "OneDrive sync is not configured on this server."
_ALREADY_CONNECTED = "This Organization is already connected to OneDrive. Disconnect it first."
_NOT_CONNECTED = "This Organization isn't connected to OneDrive."
_READ_DENIED = "You don't have permission to view OneDrive sync for this organization."
_MANAGE_DENIED = "You don't have permission to manage OneDrive sync for this organization."
_ADMIN_APPROVAL_NEEDED = "A Microsoft Global Administrator needs to approve Agent Barn for your organization."
_APPROVED = (
    "Agent Barn is approved for your organization. The person connecting can now connect OneDrive. "
    "You can close this window."
)
_SIGN_IN_EXPIRED = "This sign-in has expired. Please try again."
_SIGN_IN_INCOMPLETE = "Microsoft did not complete the sign-in. Please try again."
_SIGN_IN_NOT_YOURS = "This sign-in has expired or was started by someone else. Please connect again."
_SIGN_IN_REFUSED = "Microsoft refused the sign-in. Please connect again."
_SIGN_IN_WITHOUT_TENANT = "Microsoft didn't say which organization you signed in to. Sign in with a work account."
_SITE_ADMINISTRATION_MISSING = (
    "Microsoft didn't grant permission to manage SharePoint sites. Sign in as a SharePoint or Microsoft 365 "
    "administrator."
)
_UNREACHABLE = "Microsoft couldn't be reached. Please try again."
_REQUIRED_PERMISSIONS = frozenset({SITE_GRANT_PERMISSION, READ_PERMISSION})
FOLDER_NAME = "Agent Barn"
GRANT_DISPLAY_NAME = "Agent Barn"
GRANT_ROLE = "write"
_SIGN_IN_NEEDED = "Your Microsoft sign-in has expired. Start connecting OneDrive again."
_SEARCH_TERM_NEEDED = "Type part of the SharePoint site's name to search."
_SITE_NOT_FOUND = "Couldn't find that SharePoint site. Search again and pick it from the list."
_NOT_A_SITE_ADMINISTRATOR = "Sign in as a SharePoint administrator who is a member of this site, then try again."
_THROTTLED = "Microsoft is limiting requests right now. Wait a few minutes, then try again."
_FOLDER_FAILED = "Agent Barn couldn't create its folder on that site, so it was not connected. Please try again."
_ANOTHER_TENANT = "Sign in with an account from the Microsoft organization that connected OneDrive."
_SITE_HELD_BY_AGENT = (
    "An Agent in this Organization already has SharePoint access to this site. Remove it there, or pick another site."
)

OneDriveSyncPurpose = Literal["connect", "disconnect"]


@dataclass(frozen=True)
class OneDriveSyncState:
    organization_id: UUID
    # The person who started the flow; only they can complete it.
    user_id: UUID
    purpose: OneDriveSyncPurpose
    code_verifier: str


def redirect_uri(config: Config) -> str:
    return f"{config.web_app_url}/api/v1/integrations/onedrive-sync/callback"


def encode_state(config: Config, state: OneDriveSyncState, *, ttl_seconds: int = _STATE_TTL_SECONDS) -> str:
    payload = {
        "typ": _STATE_TYPE,
        "organization_id": str(state.organization_id),
        "user_id": str(state.user_id),
        "purpose": state.purpose,
        # The state passes through Microsoft and the browser; the verifier proves the code
        # redemption is ours, so it travels encrypted.
        "verifier": encrypt_token(state.code_verifier, config.agent_token_encryption_key),
        "exp": int(time.time()) + ttl_seconds,
    }
    return jwt.encode(payload, config.secret_signing_key, algorithm=JWT_ENCODING_ALGORITHM)


def decode_state(token: str, config: Config) -> OneDriveSyncState | None:
    """The state this server signed for OneDrive sync, or None if forged, expired or another flow's."""
    try:
        payload = jwt.decode(token, config.secret_signing_key, algorithms=[JWT_ENCODING_ALGORITHM])
        if payload.get("typ") != _STATE_TYPE or payload.get("purpose") not in ("connect", "disconnect"):
            return None
        return OneDriveSyncState(
            organization_id=UUID(payload["organization_id"]),
            user_id=UUID(payload["user_id"]),
            purpose=payload["purpose"],
            code_verifier=decrypt_token(payload["verifier"], config.agent_token_encryption_key),
        )
    except Exception:
        return None


def callback_html(
    config: Config,
    *,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    approved: bool = False,
) -> HTMLResponse:
    """A page that posts the result to the window that opened the popup, then closes. A Global
    Administrator approving from a forwarded link lands here too, so it reads sensibly on its own."""
    if error is not None:
        message: dict = {"type": MESSAGE_TYPE, "error": error}
        blurb = "Sign-in failed. You can close this window."
    elif approved:
        message = {"type": MESSAGE_TYPE, "adminConsent": True}
        blurb = _APPROVED
    else:
        message = {"type": MESSAGE_TYPE, "code": code, "state": state}
        blurb = "Sign-in complete. You can close this window."

    # Escaping "<", ">" and "&" keeps the JSON inert inside the script block, so an error
    # from the unauthenticated query string cannot end it early.
    def _script_safe(value: object) -> str:
        return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

    html = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Microsoft sign-in</title></head>
<body style="font-family: system-ui, -apple-system, sans-serif; padding: 24px; color: #333;">
<p>{blurb}</p>
<script>
  (function () {{
    var msg = {_script_safe(message)};
    if (window.opener) {{
      window.opener.postMessage(msg, {_script_safe(config.web_app_url)});
      window.close();
    }}
  }})();
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@inject
@singleton
@dataclass
class OneDriveSyncService:
    repository: OneDriveSyncRepository
    permission_policy: PermissionPolicy
    identity: MicrosoftIdentityClient
    graph_sites: MicrosoftGraphSites
    sharepoint: SharePointService
    config: Config

    def status(self, organization_id: UUID, context: CurrentUserContext) -> OneDriveSyncConnectionRead:
        self.permission_policy.require(context, organization_id, PermissionKey.ORGANIZATION_READ, detail=_READ_DENIED)
        if not self.config.is_onedrive_sync_enabled:
            return OneDriveSyncConnectionRead(available=False)
        approval_url = build_app_permission_consent_url(
            tenant_id=MULTI_TENANT_AUTHORITY,
            client_id=self.config.onedrive_sync_client_id,
            redirect_uri=redirect_uri(self.config),
        )
        connection = self.repository.get_open(organization_id)
        if connection is None or _expired_pending(connection):
            return OneDriveSyncConnectionRead(available=True, approval_url=approval_url)
        return OneDriveSyncConnectionRead(
            available=True,
            status=connection.status,
            site_name=connection.site_name,
            site_url=connection.site_url,
            folder_web_url=connection.folder_web_url,
            connected_at=connection.connected_at,
            approval_url=approval_url,
        )

    def authorize_url(self, organization_id: UUID, purpose: OneDriveSyncPurpose, context: CurrentUserContext) -> str:
        self._require_manage(organization_id, context)
        self._require_configured()
        connection = self.repository.get_open(organization_id)
        active = connection is not None and connection.status == OneDriveSyncStatus.ACTIVE
        if purpose == "connect" and active:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_ALREADY_CONNECTED)
        if purpose == "disconnect" and not active:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_NOT_CONNECTED)
        verifier, challenge = pkce_pair()
        state = OneDriveSyncState(
            organization_id=organization_id, user_id=context.user.id, purpose=purpose, code_verifier=verifier
        )
        # Straight to sign-in: once a Global Administrator has approved the app for the
        # organization, any SharePoint Administrator can connect without them. Where it isn't
        # approved yet, Microsoft says so and the callback explains who must approve.
        return self._sign_in_url(encode_state(self.config, state), challenge)

    def callback_page(
        self,
        code: str | None,
        state: str | None,
        error: str | None,
        error_description: str | None = None,
        admin_consent: str | None = None,
    ) -> Response:
        # Microsoft reports a refused consent with admin_consent=True as well, so the error
        # is read before anything else.
        if error:
            description = error_description or ""
            if error == "consent_required" or any(known in description for known in _ADMIN_APPROVAL_ERROR_CODES):
                return callback_html(self.config, error=_ADMIN_APPROVAL_NEEDED)
            return callback_html(self.config, error=f"Microsoft sign-in was cancelled or failed ({error}).")
        if (admin_consent or "").lower() == "true":
            return callback_html(self.config, approved=True)
        if state is None or decode_state(state, self.config) is None:
            return callback_html(self.config, error=_SIGN_IN_EXPIRED)
        if not code:
            return callback_html(self.config, error=_SIGN_IN_INCOMPLETE)
        return callback_html(self.config, code=code, state=state)

    def complete_sign_in(
        self, organization_id: UUID, code: str, state_token: str, context: CurrentUserContext
    ) -> OneDriveSyncConnectionRead:
        """Redeem the administrator's code and hold their delegated token on a pending connection
        until a site is chosen. The tenant is the one Microsoft names in the id_token."""
        self._require_manage(organization_id, context)
        self._require_configured()
        state = self._verified_state(state_token, "connect", organization_id, context)
        tokens, tenant_id = self._redeem(code, state)
        try:
            self.repository.create_pending(
                organization_id,
                tenant_id=tenant_id,
                connected_by_user_id=context.user.id,
                pending_access_token=encrypt_token(tokens.access_token, self.config.agent_token_encryption_key),
                pending_expires_at=datetime.now(UTC) + timedelta(seconds=tokens.expires_in),
            )
        except OneDriveSyncConnectionConflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_ALREADY_CONNECTED) from exc
        return self.status(organization_id, context)

    def sites(self, organization_id: UUID, search: str, context: CurrentUserContext) -> list[OneDriveSyncSiteRead]:
        """SharePoint sites the signed-in administrator can see that match ``search``."""
        self._require_manage(organization_id, context)
        self._require_configured()
        query = search.strip()
        if not query:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_SEARCH_TERM_NEEDED)
        _, token = self._signed_in(organization_id)
        try:
            found = self.graph_sites.search_sites(token, query)
        except SiteAccessRefused as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_SITE_ADMINISTRATION_MISSING) from exc
        except SitesThrottled as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_THROTTLED) from exc
        except SiteNotFound, SitesUnavailable:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_UNREACHABLE) from None
        return [OneDriveSyncSiteRead(id=site.id, name=site.name, web_url=site.web_url) for site in found]

    def choose_site(
        self, organization_id: UUID, site_id: str, context: CurrentUserContext
    ) -> OneDriveSyncConnectionRead:
        """Grant the platform app write on the chosen site, ensure the Agent Barn folder as the app,
        and activate the connection. A failure after the grant takes the grant back, so the site is
        never left granted to a connection that stayed pending."""
        self._require_manage(organization_id, context)
        self._require_configured()
        connection, token = self._signed_in(organization_id)
        try:
            site = self.graph_sites.get_site(token, site_id)
            if site.id.lower() in self.sharepoint.organization_site_ids(organization_id):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_SITE_HELD_BY_AGENT)
            permission_id = self.graph_sites.grant_site(
                token,
                site_id=site.id,
                app_id=self.config.onedrive_sync_client_id,
                display_name=GRANT_DISPLAY_NAME,
                role=GRANT_ROLE,
            )
        except SiteNotFound as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_SITE_NOT_FOUND) from exc
        except SiteAccessRefused as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_NOT_A_SITE_ADMINISTRATOR) from exc
        except SitesThrottled as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_THROTTLED) from exc
        except SitesUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_UNREACHABLE) from exc
        try:
            app_tokens = self.identity.client_credentials(
                tenant_id=connection.tenant_id,
                client_id=self.config.onedrive_sync_client_id,
                client_secret=self.config.onedrive_sync_client_secret,
            )
            folder = self.graph_sites.ensure_folder(app_tokens.access_token, site_id=site.id, name=FOLDER_NAME)
        except (
            MicrosoftIdentityError,
            MicrosoftIdentityUnavailable,
            SiteAccessRefused,
            SiteNotFound,
            SitesUnavailable,
        ) as exc:
            logger.warning(
                "OneDrive sync folder setup failed for organization %s: %s", organization_id, type(exc).__name__
            )
            self._revoke_quietly(token, site.id, permission_id)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_FOLDER_FAILED) from exc
        activated = self.repository.activate(
            connection.id,
            site_id=site.id,
            site_name=site.name,
            site_url=site.web_url,
            folder_item_id=folder.item_id,
            folder_web_url=folder.web_url,
            permission_id=permission_id,
        )
        if activated is None:
            self._revoke_quietly(token, site.id, permission_id)
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_SIGN_IN_NEEDED)
        return self.status(organization_id, context)

    def disconnect(
        self, organization_id: UUID, code: str, state_token: str, context: CurrentUserContext
    ) -> OneDriveSyncConnectionRead:
        """Revoke the platform app's site grant with the administrator's fresh delegated token, then
        close the connection. An app granted only ``write`` cannot remove its own grant, which is
        why disconnecting needs this sign-in. The folder is left in place."""
        self._require_manage(organization_id, context)
        self._require_configured()
        state = self._verified_state(state_token, "disconnect", organization_id, context)
        connection = self.repository.get_open(organization_id)
        if (
            connection is None
            or connection.status != OneDriveSyncStatus.ACTIVE
            or connection.site_id is None
            or connection.permission_id is None
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_NOT_CONNECTED)
        tokens, tenant_id = self._redeem(code, state)
        if tenant_id.lower() != connection.tenant_id.lower():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_ANOTHER_TENANT)
        try:
            self.graph_sites.revoke_site(
                tokens.access_token, site_id=connection.site_id, permission_id=connection.permission_id
            )
        except SiteAccessRefused as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_NOT_A_SITE_ADMINISTRATOR) from exc
        except SitesThrottled as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_THROTTLED) from exc
        except SitesUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_UNREACHABLE) from exc
        self.repository.mark_disconnected(connection.id)
        return self.status(organization_id, context)

    def abandon_pending(self, organization_id: UUID, context: CurrentUserContext) -> None:
        """Forget an unfinished connection. An active connection is left alone; disconnect it instead."""
        self._require_manage(organization_id, context)
        self.repository.delete_pending(organization_id)

    def _verified_state(
        self, state_token: str, purpose: OneDriveSyncPurpose, organization_id: UUID, context: CurrentUserContext
    ) -> OneDriveSyncState:
        """The signed state, only if it was issued to this caller, for this Organization and purpose."""
        state = decode_state(state_token, self.config)
        if (
            state is None
            or state.purpose != purpose
            or state.organization_id != organization_id
            or state.user_id != context.user.id
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_SIGN_IN_NOT_YOURS)
        return state

    def _redeem(self, code: str, state: OneDriveSyncState) -> tuple[MicrosoftTokens, str]:
        """Redeem the code as the platform app; returns the tokens and the tenant Microsoft names
        in the id_token. Both site permissions must have been granted."""
        try:
            tokens = self.identity.exchange_code(
                tenant_id=MULTI_TENANT_AUTHORITY,
                client_id=self.config.onedrive_sync_client_id,
                code=code,
                redirect_uri=redirect_uri(self.config),
                code_verifier=state.code_verifier,
                scopes=SIGN_IN_SCOPES,
                client_secret=self.config.onedrive_sync_client_secret,
            )
        except MicrosoftIdentityError as exc:
            logger.info("OneDrive sync sign-in refused by Microsoft: %s", exc.error)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_SIGN_IN_REFUSED) from exc
        except MicrosoftIdentityUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_UNREACHABLE) from exc
        tenant_id = str(claims_from_id_token(tokens.id_token).get("tid") or "")
        if not tenant_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_SIGN_IN_WITHOUT_TENANT)
        if not _REQUIRED_PERMISSIONS <= granted_permissions(tokens.scope.split()):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_SITE_ADMINISTRATION_MISSING)
        return tokens, tenant_id

    def _signed_in(self, organization_id: UUID) -> tuple[OneDriveSyncConnection, str]:
        """The pending connection and its administrator's delegated token, while the sign-in is fresh."""
        connection = self.repository.get_open(organization_id)
        if (
            connection is None
            or connection.status != OneDriveSyncStatus.PENDING
            or connection.pending_access_token is None
            or _expired_pending(connection)
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_SIGN_IN_NEEDED)
        return connection, decrypt_token(connection.pending_access_token, self.config.agent_token_encryption_key)

    def _revoke_quietly(self, token: str, site_id: str, permission_id: str) -> None:
        try:
            self.graph_sites.revoke_site(token, site_id=site_id, permission_id=permission_id)
        except SiteAccessRefused, SitesUnavailable:
            logger.warning("OneDrive sync could not take back site grant %s on %s", permission_id, site_id)

    def _sign_in_url(self, state: str, code_challenge: str) -> str:
        return build_authorize_url(
            tenant_id=MULTI_TENANT_AUTHORITY,
            client_id=self.config.onedrive_sync_client_id,
            redirect_uri=redirect_uri(self.config),
            scopes=SIGN_IN_SCOPES,
            state=state,
            code_challenge=code_challenge,
        )

    def _require_manage(self, organization_id: UUID, context: CurrentUserContext) -> None:
        self.permission_policy.require(
            context, organization_id, PermissionKey.ORGANIZATION_UPDATE, detail=_MANAGE_DENIED
        )

    def _require_configured(self) -> None:
        if not self.config.is_onedrive_sync_enabled:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_NOT_CONFIGURED)


def _expired_pending(connection: OneDriveSyncConnection) -> bool:
    return (
        connection.status == OneDriveSyncStatus.PENDING
        and connection.pending_expires_at is not None
        and connection.pending_expires_at <= datetime.now(UTC)
    )
