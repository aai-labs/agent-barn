"""SharePoint for an agent, signed in with Microsoft on the agent's Teams app.

Two modes, one per agent. *Delegated* (the default, described below) reaches whatever the
person who signed in can open. *Selected sites* reaches only sites an administrator granted:
see ``_complete_site_grant`` and ``access_token``.

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

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal, Self
from uuid import UUID, uuid4

import jwt
from fastapi import HTTPException, status
from fastapi.responses import HTMLResponse
from injector import inject, singleton
from pydantic import BaseModel

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.microsoft_graph_scopes import (
    SELECTED_SITES_PERMISSION,
    SITE_GRANT_PERMISSION,
    granted_permissions,
    missing_sharepoint_permissions,
    sharepoint_scopes,
    site_grant_scopes,
)
from api.domains.agents.microsoft_graph_sites import (
    MicrosoftGraphSites,
    SiteAccessRefused,
    SiteChangeRejected,
    SiteNotFound,
    SitesThrottled,
    SitesUnavailable,
)
from api.domains.agents.microsoft_identity import (
    MicrosoftIdentityClient,
    MicrosoftIdentityError,
    MicrosoftIdentityUnavailable,
    MicrosoftTokens,
    build_admin_consent_url,
    build_app_permission_consent_url,
    build_authorize_url,
    claims_from_id_token,
    pkce_pair,
)
from api.domains.agents.models import (
    PROVIDER_DISPLAY_NAMES,
    Agent,
    AgentSecret,
    GrantedSite,
    SecretProvider,
    SharePointContent,
    decrypt_content,
    encrypt_content,
)
from api.domains.agents.repository import AgentRepository
from api.domains.agents.sharepoint_sites import normalize_site_url
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

SharePointMode = Literal["delegated", "selected_sites"]

# Each site rides in the signed state through Microsoft and the browser; keep it a sane size.
_MAX_SITES = 50

_UNREACHABLE = "Microsoft couldn't be reached. Please try again."
_NOT_CONNECTED = "SharePoint isn't connected for this agent. Ask someone to set it up in the agent's Integrations."

# A cached app-only token is handed out only while it has longer than this left.
_TOKEN_MARGIN = timedelta(minutes=5)
_NOT_AN_ADMINISTRATOR = (
    "Microsoft didn't let this account manage SharePoint site permissions. Sign in as a SharePoint "
    "or Microsoft 365 administrator."
)
_THROTTLED = "Microsoft is limiting requests right now. Wait a few minutes, then sign in again."
_ANOTHER_SIGN_IN = "Another SharePoint sign-in for this agent is finishing. Try again in a moment."
SITES_STILL_GRANTED = (
    "SharePoint sites are still granted to this agent's Microsoft Teams app. Remove all sites under "
    "SharePoint in the agent's Integrations first; an administrator signs in to do it."
)


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
    mode: SharePointMode = "delegated"
    # Selected-sites mode: every site the agent should reach once the sign-in completes,
    # already reduced to site roots. Sites granted before and missing here are revoked.
    sites: tuple[str, ...] = ()
    # Selected-sites mode: revoke every granted site and disconnect SharePoint.
    remove_all: bool = False


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
        "mode": state.mode,
        "sites": list(state.sites),
        "remove_all": state.remove_all,
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
            mode="selected_sites" if payload.get("mode") == "selected_sites" else "delegated",
            sites=tuple(str(site) for site in payload.get("sites", [])),
            remove_all=payload.get("remove_all") is True,
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
    # Selected-sites mode: approves the application permissions listed on the app, which
    # must include Sites.Selected.
    app_permission_consent_url: str


class SharePointAccessTokenRead(BaseModel):
    access_token: str
    expires_at: datetime


class SharePointSignInRead(BaseModel):
    """Who signed in and what the agent reaches. Also the agent's current SharePoint access."""

    email: str
    read_only: bool
    mode: SharePointMode = "delegated"
    # Selected-sites mode only: the granted sites' URLs. Never the grant ids.
    sites: list[str] = []

    @classmethod
    def of(cls, content: SharePointContent) -> Self:
        return cls(
            email=content.email,
            read_only=content.read_only,
            mode=content.mode,
            sites=[site.url for site in content.sites],
        )


@inject
@singleton
@dataclass
class SharePointService:
    authorization: AgentAuthorization
    repository: AgentRepository
    communications: CommunicationsService
    identity: MicrosoftIdentityClient
    graph_sites: MicrosoftGraphSites
    event_delivery_dispatcher: EventDeliveryDispatcher
    config: Config
    # App-only tokens per Teams app, until shortly before they lapse: pods ask for one per
    # command. Keyed by a hash of the secret too, so a rotated secret is never served a token
    # minted with the old one. Per process, like the Teams bot's own token cache.
    _app_tokens: dict[tuple[str, str, str], tuple[str, datetime]] = field(default_factory=dict, init=False)
    _app_tokens_lock: threading.Lock = field(default_factory=threading.Lock, init=False)

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
            app_permission_consent_url=build_app_permission_consent_url(
                tenant_id=app.tenant_id, client_id=app.app_id, redirect_uri=redirect_uri
            ),
        )

    def current(self, agent_id: UUID, context: CurrentUserContext) -> SharePointSignInRead:
        """The agent's SharePoint access as the UI shows it. Nothing secret."""
        self._require_manage(agent_id, context)
        content = self._stored_content(agent_id)
        if content is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="SharePoint isn't connected for this agent."
            )
        return SharePointSignInRead.of(content)

    def authorize_url(
        self,
        agent_id: UUID,
        connection_id: UUID,
        read_only: bool,
        context: CurrentUserContext,
        *,
        mode: SharePointMode = "delegated",
        sites: list[str] | None = None,
        remove_all: bool = False,
    ) -> str:
        """Where to send the browser to sign in.

        In selected-sites mode the person must be an administrator: the sign-in asks for
        ``Sites.FullControl.All`` to grant the Teams app each site in ``sites``, which are
        the complete set the agent should reach afterwards. With ``remove_all`` it revokes
        every granted site instead, and SharePoint is disconnected.
        """
        self._require_manage(agent_id, context)
        if remove_all:
            current = self._stored_content(agent_id)
            if current is None or current.mode != "selected_sites":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="No SharePoint sites are granted to this agent."
                )
            mode, site_roots = "selected_sites", ()
        elif mode == "selected_sites":
            site_roots = _site_roots(sites or [])
        else:
            self._refuse_while_sites_granted(agent_id)
            site_roots = ()
        app = self.communications.get_teams_app_identity(agent_id, connection_id)
        verifier, challenge = pkce_pair()
        state = SignInState(
            agent_id=agent_id,
            connection_id=connection_id,
            user_id=context.user.id,
            read_only=read_only,
            code_verifier=verifier,
            mode=mode,
            sites=site_roots,
            remove_all=remove_all,
        )
        return build_authorize_url(
            tenant_id=app.tenant_id,
            client_id=app.app_id,
            redirect_uri=sign_in_redirect_uri(self.config),
            scopes=_sign_in_scopes(state),
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
    ) -> SharePointSignInRead | None:
        """Finish a sign-in. None when it removed every site, which disconnects SharePoint."""
        state = decode_sign_in_state(state_token, self.config)
        if state is None or state.agent_id != agent_id or state.user_id != context.user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This sign-in has expired or wasn't started by you. Please try again.",
            )
        agent = self._require_manage(agent_id, context)
        # Held through the save: a second sign-in finishing meanwhile would read the same granted
        # sites and overwrite this one's result.
        with self.repository.sharepoint_sign_in_lock(agent_id) as acquired:
            if not acquired:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_ANOTHER_SIGN_IN)
            return self._complete_sign_in(agent, code, state, context)

    def _complete_sign_in(
        self, agent: Agent, code: str, state: SignInState, context: CurrentUserContext
    ) -> SharePointSignInRead | None:
        agent_id = agent.id
        if state.mode == "delegated":
            # Started before the sites were granted; a personal sign-in would lose track of them.
            self._refuse_while_sites_granted(agent_id)
        app = self.communications.get_teams_app_identity(agent_id, state.connection_id)

        try:
            tokens = self.identity.exchange_code(
                tenant_id=app.tenant_id,
                client_id=app.app_id,
                code=code,
                redirect_uri=sign_in_redirect_uri(self.config),
                code_verifier=state.code_verifier,
                scopes=_sign_in_scopes(state),
            )
        except MicrosoftIdentityError as exc:
            logger.info("SharePoint sign-in code exchange refused: %s", exc.error)
            if any(known in exc.description for known in _PUBLIC_CLIENT_ERROR_CODES):
                detail = _PUBLIC_CLIENT_SETUP_NEEDED
            else:
                detail = "Microsoft didn't accept the sign-in. Please try again."
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc
        except MicrosoftIdentityUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_UNREACHABLE) from exc

        claims = claims_from_id_token(tokens.id_token)
        tenant_id = str(claims.get("tid") or "")
        if not _same_tenant(app.tenant_id, tenant_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sign in with an account from the organization this agent's Microsoft Teams app belongs to.",
            )
        if state.mode == "selected_sites":
            return self._complete_site_grant(agent, app.app_id, state, tokens, tenant_id, claims, context)
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
        return SharePointSignInRead.of(content)

    def _complete_site_grant(
        self,
        agent: Agent,
        app_id: str,
        state: SignInState,
        tokens: MicrosoftTokens,
        tenant_id: str,
        claims: dict,
        context: CurrentUserContext,
    ) -> SharePointSignInRead | None:
        """Reconcile the Teams app's site grants with ``state.sites``, using the administrator's token.

        New sites are granted, removed ones revoked, and kept ones left alone unless the access
        level changed, in which case their grants are updated in place. Grants recorded for a
        different app (the Teams connection now uses another one) are all replaced. The token is
        used only here and never stored. Ordered so a failure leaves the record true to
        Microsoft, or one sign-in away from it: every new site is looked up before anything
        changes, a failed grant or level change takes back this attempt's grants and puts changed
        levels back, and a grant that couldn't be removed stays on record so the next sign-in
        tries again.
        """
        if SITE_GRANT_PERMISSION not in granted_permissions(tokens.scope.split()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Microsoft didn't grant permission to manage SharePoint sites. Sign in as a SharePoint "
                    "or Microsoft 365 administrator."
                ),
            )
        token = tokens.access_token
        previous = self._stored_content(agent.id)
        if state.remove_all:
            return self._remove_all_sites(agent, token, previous, context)
        role = "read" if state.read_only else "write"
        recorded = previous.sites if previous is not None and previous.mode == "selected_sites" else []
        same_app = previous is not None and previous.client_id == app_id
        existing = {site.url: site for site in recorded} if same_app else {}
        level_changed = previous is not None and previous.read_only != state.read_only
        kept = {url: site for url, site in existing.items() if url in state.sites}
        removed = [site for site in recorded if site.url not in kept]

        updated: list[GrantedSite] = []
        granted: dict[str, GrantedSite] = {}
        try:
            site_ids = {url: self.graph_sites.resolve_site_id(token, url) for url in state.sites if url not in kept}
            try:
                if level_changed:
                    for site in kept.values():
                        try:
                            self.graph_sites.update_site_role(
                                token, site_id=site.site_id, permission_id=site.permission_id, role=role
                            )
                        except SiteNotFound:
                            raise SiteNotFound(site.url) from None
                        except SiteChangeRejected:
                            raise SiteChangeRejected(site.url) from None
                        updated.append(site)
                for url, site_id in site_ids.items():
                    try:
                        permission_id = self.graph_sites.grant_site(
                            token, site_id=site_id, app_id=app_id, display_name=agent.name, role=role
                        )
                    except SiteNotFound:
                        raise SiteNotFound(url) from None
                    except SiteChangeRejected:
                        raise SiteChangeRejected(url) from None
                    granted[url] = GrantedSite(url=url, site_id=site_id, permission_id=permission_id)
            except SiteAccessRefused, SiteNotFound, SitesUnavailable:
                for site in granted.values():
                    self._revoke_quietly(token, site)
                # Only a level change puts sites in `updated`, so a previous record exists.
                previous_role = "read" if previous is not None and previous.read_only else "write"
                for site in updated:
                    self._restore_role_quietly(token, site, previous_role)
                raise
        except SiteNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Couldn't find the SharePoint site {exc}. Check the address, and that the account you "
                    "signed in with can open it."
                ),
            ) from exc
        except SiteAccessRefused as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_NOT_AN_ADMINISTRATOR) from exc
        except SitesThrottled as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_THROTTLED) from exc
        except SiteChangeRejected as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Microsoft wouldn't change access to {exc}. Check the site in SharePoint, then sign in again.",
            ) from exc
        except SitesUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_UNREACHABLE) from exc

        still_granted = self._revoke_each(token, removed, agent.id)
        content = SharePointContent(
            mode="selected_sites",
            connection_id=str(state.connection_id),
            tenant_id=tenant_id,
            client_id=app_id,
            email=str(claims.get("preferred_username") or claims.get("email") or "unknown account"),
            scopes=[SELECTED_SITES_PERMISSION],
            read_only=state.read_only,
            sites=[kept.get(url) or granted[url] for url in state.sites] + still_granted,
        )
        self._save_secret(agent, content, context)
        if still_granted:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "The new sites are saved, but access to "
                    + ", ".join(site.url for site in still_granted)
                    + " couldn't be removed. Sign in again to retry."
                ),
            )
        return SharePointSignInRead.of(content)

    def _remove_all_sites(
        self, agent: Agent, token: str, previous: SharePointContent | None, context: CurrentUserContext
    ) -> None:
        """Revoke every recorded grant, then forget SharePoint. Grants that couldn't be revoked
        stay on record, so the agent keeps only those and the next removal sign-in retries."""
        recorded = previous.sites if previous is not None and previous.mode == "selected_sites" else []
        still_granted = self._revoke_each(token, recorded, agent.id)
        if still_granted:
            assert previous is not None
            self._save_secret(agent, previous.model_copy(update={"sites": still_granted}), context)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Access to "
                    + ", ".join(site.url for site in still_granted)
                    + " couldn't be removed. Sign in again to retry."
                ),
            )
        delivery_ids = self.repository.delete_secret_with_event(
            agent.id,
            SecretProvider.SHAREPOINT,
            organization_id=agent.organization_id,
            agent_name=agent.name,
            actor=resolve_actor_identity(context, agent.organization_id),
            actor_display=context.user.full_name or context.user.email,
        )
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)

    def _revoke_each(self, token: str, sites: list[GrantedSite], agent_id: UUID) -> list[GrantedSite]:
        """Revoke each site's grant; returns the ones Microsoft didn't remove."""
        still_granted: list[GrantedSite] = []
        for site in sites:
            try:
                self.graph_sites.revoke_site(token, site_id=site.site_id, permission_id=site.permission_id)
            except SiteAccessRefused, SitesUnavailable:
                logger.warning("SharePoint site grant could not be removed for agent %s", agent_id)
                still_granted.append(site)
        return still_granted

    def refuse_retiring_teams_app(self, agent_id: UUID, connection_id: UUID, context: CurrentUserContext) -> None:
        """409 when removing the Teams connection would leave granted sites behind.

        A released app can be connected to another agent, whose app-only tokens would reach the
        sites still granted to it.
        """
        if self._holds_sites_on(agent_id, connection_id) is not None:
            self._require_manage(agent_id, context)
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=SITES_STILL_GRANTED)

    def refuse_swapping_teams_app(
        self, agent_id: UUID, connection_id: UUID, credentials: dict | None, context: CurrentUserContext
    ) -> None:
        """409 when a connection update points it at another Teams app while sites are granted to
        this one, which would release it like removing the connection does. Keeping the app (a
        rotated secret, say) is fine."""
        content = self._holds_sites_on(agent_id, connection_id)
        if content is None or credentials is None:
            return
        same_app = str(credentials.get("app_id") or "").lower() == content.client_id.lower()
        if same_app and _same_tenant(str(credentials.get("tenant_id") or ""), content.tenant_id):
            return
        self._require_manage(agent_id, context)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=SITES_STILL_GRANTED)

    def _holds_sites_on(self, agent_id: UUID, connection_id: UUID) -> SharePointContent | None:
        """The agent's selected-sites credential, if its sites are granted to this connection's app."""
        content = self._stored_content(agent_id)
        if content is None or content.mode != "selected_sites" or content.connection_id != str(connection_id):
            return None
        return content

    def _refuse_while_sites_granted(self, agent_id: UUID) -> None:
        content = self._stored_content(agent_id)
        if content is not None and content.mode == "selected_sites":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=SITES_STILL_GRANTED)

    def access_token(self, agent_id: UUID) -> SharePointAccessTokenRead:
        """A short-lived app-only token for an agent in selected-sites mode.

        It reaches only the sites granted to the agent's Teams app. Minted here with the Teams
        app's secret, so aai-cli needs no Microsoft credential. Not a security boundary: native
        Teams gives the pod the same secret, for the bot, and any token minted with it reaches
        the same sites. Callers authenticate the agent first (its ingest key); there is no user
        here.
        """
        content = self._stored_content(agent_id)
        if content is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_CONNECTED)
        if content.mode != "selected_sites":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This agent's SharePoint uses a personal sign-in, which issues no tokens here.",
            )
        app = self.communications.get_teams_app_credentials(agent_id, UUID(content.connection_id))
        key = (app.tenant_id, app.app_id, hashlib.sha256(app.app_password.encode()).hexdigest())
        now = datetime.now(UTC)
        with self._app_tokens_lock:
            cached = self._app_tokens.get(key)
        if cached is not None and cached[1] - now > _TOKEN_MARGIN:
            return SharePointAccessTokenRead(access_token=cached[0], expires_at=cached[1])

        try:
            tokens = self.identity.client_credentials(
                tenant_id=app.tenant_id, client_id=app.app_id, client_secret=app.app_password
            )
        except MicrosoftIdentityError as exc:
            logger.info("SharePoint app-only token refused for agent %s: %s", agent_id, exc.error)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Microsoft refused the agent's Microsoft Teams app. Check its client secret is current "
                    "and that an administrator approved Sites.Selected for it."
                ),
            ) from exc
        except MicrosoftIdentityUnavailable as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_UNREACHABLE) from exc
        expires_at = now + timedelta(seconds=tokens.expires_in)
        with self._app_tokens_lock:
            self._app_tokens[key] = (tokens.access_token, expires_at)
        return SharePointAccessTokenRead(access_token=tokens.access_token, expires_at=expires_at)

    def _revoke_quietly(self, token: str, site: GrantedSite) -> None:
        try:
            self.graph_sites.revoke_site(token, site_id=site.site_id, permission_id=site.permission_id)
        except SiteAccessRefused, SitesUnavailable:
            logger.warning("SharePoint site grant could not be taken back after a failed sign-in")

    def _restore_role_quietly(self, token: str, site: GrantedSite, role: str) -> None:
        try:
            self.graph_sites.update_site_role(token, site_id=site.site_id, permission_id=site.permission_id, role=role)
        except SiteAccessRefused, SiteNotFound, SitesUnavailable:
            logger.warning("SharePoint site access level could not be put back after a failed sign-in")

    def _stored_content(self, agent_id: UUID) -> SharePointContent | None:
        secret = self.repository.get_secret(agent_id, SecretProvider.SHAREPOINT)
        if secret is None or secret.content is None:
            return None
        content = decrypt_content(SecretProvider.SHAREPOINT, secret.content, self.config.agent_token_encryption_key)
        assert isinstance(content, SharePointContent)
        return content

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


def _sign_in_scopes(state: SignInState) -> tuple[str, ...]:
    return site_grant_scopes() if state.mode == "selected_sites" else sharepoint_scopes(state.read_only)


def _site_roots(sites: list[str]) -> tuple[str, ...]:
    """Each site reduced to its root, de-duplicated in the order given; 400 for a bad URL."""
    roots: list[str] = []
    for site in sites:
        try:
            root = normalize_site_url(site)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{site.strip()} isn't a SharePoint site address.",
            ) from exc
        if root not in roots:
            roots.append(root)
    if not roots:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add at least one SharePoint site.")
    if len(roots) > _MAX_SITES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Choose at most {_MAX_SITES} SharePoint sites."
        )
    return tuple(roots)
