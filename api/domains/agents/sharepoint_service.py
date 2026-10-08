"""SharePoint for an agent, signed in with Microsoft on the agent's Teams app.

The Teams app is already registered in the customer's tenant, so signing in on it needs no
app of ours and no publisher verification. The sign-in is a public client (PKCE, no secret):
the customer registers our callback under "Mobile and desktop applications", turns on "Allow
public client flows", adds the Graph permission, and, where the organization restricts user
consent, has an administrator approve it.

The resulting refresh token is stored in the Agent Secret like any other provider's
credential. At start the agent gets an aai-cli ``microsoft_delegated`` profile, which
refreshes without a secret and keeps each rotated token in aai-cli's own store. The Teams
app's secret is never read for SharePoint.
"""

import json
import logging
import time
from dataclasses import dataclass
from uuid import UUID, uuid4

import jwt
from fastapi import HTTPException, status
from fastapi.responses import HTMLResponse
from injector import inject, singleton
from pydantic import BaseModel

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.microsoft_graph_scopes import (
    granted_permissions,
    missing_sharepoint_permissions,
    sharepoint_scopes,
)
from api.domains.agents.microsoft_identity import (
    MicrosoftIdentityClient,
    MicrosoftIdentityError,
    MicrosoftIdentityUnavailable,
    build_admin_consent_url,
    build_authorize_url,
    claims_from_id_token,
    pkce_pair,
)
from api.domains.agents.models import (
    PROVIDER_DISPLAY_NAMES,
    Agent,
    AgentSecret,
    SecretProvider,
    SharePointContent,
    encrypt_content,
)
from api.domains.agents.repository import AgentRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.service import JWT_ENCODING_ALGORITHM
from api.domains.communications.service import CommunicationsService
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.events.catalog import AGENT_SECRET_ADDED, AGENT_SECRET_UPDATED
from api.domains.rbac.catalog import PermissionKey
from api.infrastructure.crypto import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

# Client-side message contract, mirrored by the UI's popup hook.
MESSAGE_TYPE = "microsoft-oauth"

_STATE_TTL_SECONDS = 600
# Distinct from the Google flow's state type, so a state signed for one is never accepted
# by the other.
_STATE_TYPE = "sharepoint_sign_in_state"

_ADMIN_APPROVAL_NEEDED = (
    "Your organization requires a Microsoft 365 administrator to approve SharePoint access for this "
    "agent's Microsoft Teams app. Ask an administrator to approve it, then sign in again."
)
# Microsoft's error codes for "this user may not consent; an administrator must": consent not
# granted and not grantable by the user (AADSTS65001), the grant needs an administrator
# (AADSTS90094), and a request sent through the admin consent workflow (AADSTS90095).
_ADMIN_APPROVAL_ERROR_CODES = ("AADSTS65001", "AADSTS90094", "AADSTS90095")

_PUBLIC_CLIENT_SETUP_NEEDED = (
    "Microsoft wouldn't finish the sign-in without the Teams app's secret. On the app's Authentication "
    "page in Microsoft Entra, make sure the redirect URI is listed under Mobile and desktop applications "
    "(not Web) and Allow public client flows is set to Yes, then sign in again."
)
# AADSTS7000218: the redemption needs client_secret or client_assertion, i.e. Microsoft treats
# the app as a confidential (web) client for this redirect URI.
_PUBLIC_CLIENT_ERROR_CODES = ("AADSTS7000218",)


def _same_tenant(configured: str, token_tid: str) -> bool:
    """Whether the id_token's tenant is the Teams app's.

    The Teams connection may hold the tenant as a GUID in any case or as a domain
    (``contoso.onmicrosoft.com``); Microsoft reports ``tid`` as a lower-case GUID. A domain
    can't be compared, but it names one organization and the sign-in already used that
    organization's authority, so any tid issued there is it. Anything else — a multi-tenant
    authority such as ``organizations`` or ``common``, or a typo — pins no organization and
    is refused, since this check is what keeps an agent inside its own.
    """
    if not token_tid:
        return False
    try:
        return UUID(configured) == UUID(token_tid)
    except ValueError:
        return "." in configured


def sign_in_redirect_uri(config: Config) -> str:
    # Must be byte-identical between the authorize URL and the code exchange, and registered
    # on the Teams app under "Mobile and desktop applications".
    return f"{config.web_app_url}/api/v1/integrations/microsoft/callback"


@dataclass(frozen=True)
class SignInState:
    agent_id: UUID
    connection_id: UUID
    # The person who started the sign-in; only they can complete it.
    user_id: UUID
    read_only: bool
    code_verifier: str


def encode_sign_in_state(config: Config, state: SignInState, *, ttl_seconds: int = _STATE_TTL_SECONDS) -> str:
    payload = {
        "typ": _STATE_TYPE,
        "agent_id": str(state.agent_id),
        "connection_id": str(state.connection_id),
        "user_id": str(state.user_id),
        "read_only": state.read_only,
        # The state passes through Microsoft and the browser; the verifier is what proves the
        # code redemption is ours, so it travels encrypted.
        "verifier": encrypt_token(state.code_verifier, config.agent_token_encryption_key),
        "exp": int(time.time()) + ttl_seconds,
    }
    return jwt.encode(payload, config.secret_signing_key, algorithm=JWT_ENCODING_ALGORITHM)


def decode_sign_in_state(token: str, config: Config) -> SignInState | None:
    """The state this server signed, or None if it is forged, expired or for another flow."""
    try:
        payload = jwt.decode(token, config.secret_signing_key, algorithms=[JWT_ENCODING_ALGORITHM])
        if payload.get("typ") != _STATE_TYPE:
            return None
        return SignInState(
            agent_id=UUID(payload["agent_id"]),
            connection_id=UUID(payload["connection_id"]),
            user_id=UUID(payload["user_id"]),
            read_only=bool(payload["read_only"]),
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
    admin_consent: bool = False,
) -> HTMLResponse:
    """A page that posts the result to the window that opened the popup, then closes.

    Carries the raw authorization code and the signed state; the opener sends both to the
    authenticated sign-in endpoint, which does the exchange. An administrator may also land
    here from an approval link opened outside the app, so the page reads sensibly on its own.
    """
    if error is not None:
        message: dict = {"type": MESSAGE_TYPE, "error": error}
        blurb = "Sign-in failed. You can close this window."
    elif admin_consent:
        message = {"type": MESSAGE_TYPE, "adminConsent": True}
        blurb = "SharePoint access is approved for your organization. You can close this window."
    else:
        message = {"type": MESSAGE_TYPE, "code": code, "state": state}
        blurb = "Sign-in complete. You can close this window."

    # json.dumps does not escape "/", so a value containing "</script>" (e.g. from the
    # unauthenticated error query parameter) would end the script block early. Escaping
    # "<", ">" and "&" keeps the JSON inert as HTML while parsing to the same JS value.
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


class SharePointSetupRead(BaseModel):
    app_id: str
    tenant_id: str
    redirect_uri: str
    # Links an administrator opens to approve SharePoint access for the whole organization.
    admin_consent_url: str
    read_only_admin_consent_url: str


class SharePointSignInRead(BaseModel):
    email: str
    read_only: bool


@inject
@singleton
@dataclass
class SharePointService:
    authorization: AgentAuthorization
    repository: AgentRepository
    communications: CommunicationsService
    identity: MicrosoftIdentityClient
    event_delivery_dispatcher: EventDeliveryDispatcher
    config: Config

    def setup(self, agent_id: UUID, connection_id: UUID, context: CurrentUserContext) -> SharePointSetupRead:
        """What the customer registers on the Teams app. All public values."""
        self._require_manage(agent_id, context)
        app = self.communications.get_teams_app_identity(agent_id, connection_id)
        redirect_uri = sign_in_redirect_uri(self.config)

        def consent(read_only: bool) -> str:
            return build_admin_consent_url(
                tenant_id=app.tenant_id, client_id=app.app_id, redirect_uri=redirect_uri, read_only=read_only
            )

        return SharePointSetupRead(
            app_id=app.app_id,
            tenant_id=app.tenant_id,
            redirect_uri=redirect_uri,
            admin_consent_url=consent(read_only=False),
            read_only_admin_consent_url=consent(read_only=True),
        )

    def authorize_url(self, agent_id: UUID, connection_id: UUID, read_only: bool, context: CurrentUserContext) -> str:
        self._require_manage(agent_id, context)
        app = self.communications.get_teams_app_identity(agent_id, connection_id)
        verifier, challenge = pkce_pair()
        state = SignInState(
            agent_id=agent_id,
            connection_id=connection_id,
            user_id=context.user.id,
            read_only=read_only,
            code_verifier=verifier,
        )
        return build_authorize_url(
            tenant_id=app.tenant_id,
            client_id=app.app_id,
            redirect_uri=sign_in_redirect_uri(self.config),
            scopes=sharepoint_scopes(read_only),
            state=encode_sign_in_state(self.config, state),
            code_challenge=challenge,
        )

    def callback_page(
        self,
        code: str | None,
        state: str | None,
        error: str | None,
        error_description: str | None = None,
        admin_consent: str | None = None,
    ) -> HTMLResponse:
        if error:
            description = error_description or ""
            if error == "consent_required" or any(known in description for known in _ADMIN_APPROVAL_ERROR_CODES):
                return callback_html(self.config, error=_ADMIN_APPROVAL_NEEDED)
            return callback_html(self.config, error=f"Microsoft sign-in was cancelled or failed ({error}).")
        if (admin_consent or "").lower() == "true":
            return callback_html(self.config, admin_consent=True)
        if not state or decode_sign_in_state(state, self.config) is None:
            return callback_html(self.config, error="This sign-in has expired. Please try again.")
        if not code:
            return callback_html(self.config, error="Microsoft did not complete the sign-in. Please try again.")
        return callback_html(self.config, code=code, state=state)

    def complete_sign_in(
        self, agent_id: UUID, code: str, state_token: str, context: CurrentUserContext
    ) -> SharePointSignInRead:
        state = decode_sign_in_state(state_token, self.config)
        if state is None or state.agent_id != agent_id or state.user_id != context.user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This sign-in has expired or wasn't started by you. Please try again.",
            )
        agent = self._require_manage(agent_id, context)
        app = self.communications.get_teams_app_identity(agent_id, state.connection_id)

        try:
            tokens = self.identity.exchange_code(
                tenant_id=app.tenant_id,
                client_id=app.app_id,
                code=code,
                redirect_uri=sign_in_redirect_uri(self.config),
                code_verifier=state.code_verifier,
                scopes=sharepoint_scopes(state.read_only),
            )
        except MicrosoftIdentityError as exc:
            logger.info("SharePoint sign-in code exchange refused: %s", exc.error)
            if any(known in exc.description for known in _PUBLIC_CLIENT_ERROR_CODES):
                detail = _PUBLIC_CLIENT_SETUP_NEEDED
            else:
                detail = "Microsoft didn't accept the sign-in. Please try again."
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc
        except MicrosoftIdentityUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Microsoft couldn't be reached. Please try again.",
            ) from exc

        claims = claims_from_id_token(tokens.id_token)
        tenant_id = str(claims.get("tid") or "")
        if not _same_tenant(app.tenant_id, tenant_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sign in with an account from the organization this agent's Microsoft Teams app belongs to.",
            )
        granted = tokens.scope.split()
        if missing_sharepoint_permissions(granted, state.read_only):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Microsoft didn't grant access to SharePoint. Check the Teams app has the SharePoint "
                    "permission, and whether your organization requires a Microsoft 365 administrator to "
                    "approve it."
                ),
            )
        if not tokens.refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Microsoft didn't allow the agent to keep access. Please sign in again.",
            )

        content = SharePointContent(
            connection_id=str(state.connection_id),
            # Microsoft's GUID, whatever form the Teams connection was set up with.
            tenant_id=tenant_id,
            client_id=app.app_id,
            email=str(claims.get("preferred_username") or claims.get("email") or "unknown account"),
            scopes=sorted(granted_permissions(granted)),
            read_only=state.read_only,
            refresh_token=tokens.refresh_token,
            sign_in_id=str(uuid4()),
        )
        self._save_secret(agent, content, context)
        return SharePointSignInRead(email=content.email, read_only=content.read_only)

    def _require_manage(self, agent_id: UUID, context: CurrentUserContext) -> Agent:
        # The same pair creating a connection needs: changing the agent and its credentials.
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_SECRET_MANAGE)
        return agent

    def _save_secret(self, agent: Agent, content: SharePointContent, context: CurrentUserContext) -> None:
        encrypted = encrypt_content(content, self.config.agent_token_encryption_key)
        existing = self.repository.get_secret(agent.id, SecretProvider.SHAREPOINT)
        if existing is not None:
            existing.content = encrypted
            existing.shared_credential_id = None
            secret, event_name = existing, AGENT_SECRET_UPDATED
        else:
            secret = AgentSecret(
                agent_id=agent.id,
                provider=SecretProvider.SHAREPOINT,
                secret_name=PROVIDER_DISPLAY_NAMES[SecretProvider.SHAREPOINT],
                content=encrypted,
            )
            event_name = AGENT_SECRET_ADDED
        delivery_ids = self.repository.save_secret_with_event(
            secret,
            event_name=event_name,
            organization_id=agent.organization_id,
            agent_name=agent.name,
            actor=resolve_actor_identity(context, agent.organization_id),
            actor_display=context.user.full_name or context.user.email,
        )
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
