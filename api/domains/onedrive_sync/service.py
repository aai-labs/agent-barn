import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import jwt
from fastapi import HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.microsoft_graph_scopes import (
    GRAPH_SCOPE_PREFIX,
    READ_PERMISSION,
    SITE_GRANT_PERMISSION,
    granted_permissions,
)
from api.domains.agents.microsoft_identity import (
    MicrosoftIdentityClient,
    MicrosoftIdentityError,
    MicrosoftIdentityUnavailable,
    build_app_permission_consent_url,
    build_authorize_url,
    claims_from_id_token,
    pkce_pair,
)
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.service import JWT_ENCODING_ALGORITHM
from api.domains.onedrive_sync.models import (
    OneDriveSyncConnection,
    OneDriveSyncConnectionRead,
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

OneDriveSyncPurpose = Literal["connect", "disconnect"]


@dataclass(frozen=True)
class OneDriveSyncState:
    organization_id: UUID
    # The person who started the flow; only they can complete it.
    user_id: UUID
    purpose: OneDriveSyncPurpose
    code_verifier: str
    code_challenge: str


def redirect_uri(config: Config) -> str:
    return f"{config.web_app_url}/api/v1/integrations/onedrive-sync/callback"


def encode_state(config: Config, state: OneDriveSyncState, *, ttl_seconds: int = _STATE_TTL_SECONDS) -> str:
    payload = {
        "typ": _STATE_TYPE,
        "organization_id": str(state.organization_id),
        "user_id": str(state.user_id),
        "purpose": state.purpose,
        # The state passes through Microsoft and the browser; the verifier proves the code
        # redemption is ours, so it travels encrypted. The challenge is public by design.
        "verifier": encrypt_token(state.code_verifier, config.agent_token_encryption_key),
        "challenge": state.code_challenge,
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
            code_challenge=str(payload["challenge"]),
        )
    except Exception:
        return None


def callback_html(
    config: Config, *, code: str | None = None, state: str | None = None, error: str | None = None
) -> HTMLResponse:
    """A page that posts the result to the window that opened the popup, then closes."""
    if error is not None:
        message: dict = {"type": MESSAGE_TYPE, "error": error}
        blurb = "Sign-in failed. You can close this window."
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
    config: Config

    def status(self, organization_id: UUID, context: CurrentUserContext) -> OneDriveSyncConnectionRead:
        self.permission_policy.require(context, organization_id, PermissionKey.ORGANIZATION_READ, detail=_READ_DENIED)
        if not self.config.is_onedrive_sync_enabled:
            return OneDriveSyncConnectionRead(available=False)
        connection = self.repository.get_open(organization_id)
        if connection is None or _expired_pending(connection):
            return OneDriveSyncConnectionRead(available=True)
        return OneDriveSyncConnectionRead(
            available=True,
            status=connection.status,
            site_name=connection.site_name,
            site_url=connection.site_url,
            folder_web_url=connection.folder_web_url,
            connected_at=connection.connected_at,
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
            organization_id=organization_id,
            user_id=context.user.id,
            purpose=purpose,
            code_verifier=verifier,
            code_challenge=challenge,
        )
        token = encode_state(self.config, state)
        if purpose == "disconnect":
            return self._sign_in_url(token, challenge)
        return build_app_permission_consent_url(
            tenant_id=MULTI_TENANT_AUTHORITY,
            client_id=self.config.onedrive_sync_client_id,
            redirect_uri=redirect_uri(self.config),
            state=token,
        )

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
        decoded = decode_state(state, self.config) if state else None
        if state is None or decoded is None:
            return callback_html(self.config, error=_SIGN_IN_EXPIRED)
        if (admin_consent or "").lower() == "true":
            return RedirectResponse(self._sign_in_url(state, decoded.code_challenge), status_code=status.HTTP_302_FOUND)
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
        state = decode_state(state_token, self.config)
        if (
            state is None
            or state.purpose != "connect"
            or state.organization_id != organization_id
            or state.user_id != context.user.id
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_SIGN_IN_NOT_YOURS)
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

    def abandon_pending(self, organization_id: UUID, context: CurrentUserContext) -> None:
        """Forget an unfinished connection. An active connection is left alone; disconnect it instead."""
        self._require_manage(organization_id, context)
        self.repository.delete_pending(organization_id)

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
