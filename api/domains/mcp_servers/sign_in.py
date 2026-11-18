"""Signing an OAuth MCP server in, for the Organization or for one Agent.

The UI opens a popup on the authorize URL from `start`. The authorization server redirects
the popup to the unauthenticated `callback`, served through the web app's own origin, which
posts the code and the signed state back to the opener. The opener then completes the
sign-in through an authenticated request. The state carries who started it, for which
server and Agent, and the PKCE verifier encrypted, because it passes through the
authorization server and the browser.
"""

import json
import time
import uuid
from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import HTTPException, status
from fastapi.responses import HTMLResponse
from injector import inject, singleton
from jwt.exceptions import InvalidTokenError

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.microsoft_identity import pkce_pair
from api.domains.agents.models import Agent
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.service import JWT_ENCODING_ALGORITHM
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.mcp_servers import oauth
from api.domains.mcp_servers.broker import McpCredentialBroker, is_oauth
from api.domains.mcp_servers.models import McpCredentialKind, McpSignInResult, McpSignInStart, OrganizationMcpServer
from api.domains.mcp_servers.repository import McpServerRepository
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.crypto import decrypt_token, encrypt_token

STATE_TYPE = "mcp_server_sign_in"
STATE_TTL_SECONDS = 600
MESSAGE_TYPE = "agentbarn-mcp-sign-in"
CALLBACK_PATH = "/api/v1/mcp-servers/oauth/callback"

RESTRICTED_DENIED = "This MCP server is restricted: only Organization Owners and Admins can change it for an Agent."


def redirect_uri(config: Config) -> str:
    """Fixed per deployment: it is the redirect URI every registered client carries."""
    return config.web_app_url.rstrip("/") + CALLBACK_PATH


@inject
@singleton
@dataclass
class McpSignInService:
    repository: McpServerRepository
    broker: McpCredentialBroker
    permission_policy: PermissionPolicy
    authorization: AgentAuthorization
    event_delivery_dispatcher: EventDeliveryDispatcher
    config: Config

    # --- who may sign in ------------------------------------------------------------

    def _authorize(
        self,
        organization_id: UUID,
        server_id: UUID,
        agent_id: UUID | None,
        context: CurrentUserContext,
    ) -> tuple[OrganizationMcpServer, Agent | None]:
        """The server, and the Agent whose credential changes (None for the Organization's).

        Organization sign-in needs `mcp_server.manage`; an Agent's own credential needs the
        Agent's `agent.update` and `agent.secret.manage`, and `mcp_server.manage` too for a
        restricted server. An Agent server signs in only for its own Agent.
        """
        self.permission_policy.require(context, organization_id, PermissionKey.ORGANIZATION_READ)
        server = self.repository.get(organization_id, server_id)
        if server is None or (server.agent_id is not None and server.agent_id != agent_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP server not found")
        if agent_id is None:
            self.permission_policy.require(
                context,
                organization_id,
                PermissionKey.MCP_SERVER_MANAGE,
                detail="Only Organization Owners and Admins can sign in MCP servers for the Organization.",
            )
            return server, None
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_SECRET_MANAGE)
        if server.restricted:
            self.permission_policy.require(
                context, organization_id, PermissionKey.MCP_SERVER_MANAGE, detail=RESTRICTED_DENIED
            )
        return server, agent

    # --- the flow ---------------------------------------------------------------------

    def start(
        self, organization_id: UUID, server_id: UUID, agent_id: UUID | None, context: CurrentUserContext
    ) -> McpSignInStart:
        server, _ = self._authorize(organization_id, server_id, agent_id, context)
        config = self.broker.server_config(server)
        if not is_oauth(config):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This MCP server does not use an OAuth sign-in.")
        verifier, challenge = pkce_pair()
        state = jwt.encode(
            {
                "typ": STATE_TYPE,
                "org": str(organization_id),
                "server": str(server.id),
                "agent": str(agent_id) if agent_id else None,
                "user": str(context.user.id),
                # A client changed since the sign-in started would not redeem this code.
                "client": config["auth"]["client_id"],
                "verifier": encrypt_token(verifier, self.config.agent_token_encryption_key),
                "nonce": uuid.uuid4().hex,
                "exp": int(time.time()) + STATE_TTL_SECONDS,
            },
            self.config.secret_signing_key,
            algorithm=JWT_ENCODING_ALGORITHM,
        )
        try:
            url = oauth.authorize_url(
                config["auth"], state=state, code_challenge=challenge, redirect_uri=redirect_uri(self.config)
            )
        except oauth.OAuthError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
        return McpSignInStart(authorize_url=url)

    def _state(self, state: str) -> dict | None:
        try:
            payload = jwt.decode(state, self.config.secret_signing_key, algorithms=[JWT_ENCODING_ALGORITHM])
        except InvalidTokenError:
            return None
        return payload if payload.get("typ") == STATE_TYPE else None

    def complete(self, organization_id: UUID, code: str, state: str, context: CurrentUserContext) -> McpSignInResult:
        payload = self._state(state)
        if payload is None or payload.get("org") != str(organization_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in has expired; start it again.")
        if payload.get("user") != str(context.user.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Someone else started this sign-in.")
        agent_id = UUID(payload["agent"]) if payload.get("agent") else None
        # Rechecked now: a permission removed, or a server restricted, since the sign-in
        # started stops it here.
        server, agent = self._authorize(organization_id, UUID(payload["server"]), agent_id, context)
        config = self.broker.server_config(server)
        if not is_oauth(config) or config["auth"].get("client_id") != payload.get("client"):
            raise HTTPException(status.HTTP_409_CONFLICT, "The server's sign-in settings changed; start it again.")
        try:
            tokens = oauth.exchange_code(
                config["auth"],
                code=code,
                code_verifier=decrypt_token(payload["verifier"], self.config.agent_token_encryption_key),
                redirect_uri=redirect_uri(self.config),
            )
        except oauth.OAuthError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"The sign-in could not be completed: {exc}") from None
        deliveries = self.repository.put_credential_with_event(
            server,
            agent,
            kind=McpCredentialKind.OAUTH.value,
            credentials_encrypted=encrypt_token(json.dumps(tokens.as_grant()), self.config.agent_token_encryption_key),
            user_id=context.user.id,
            actor=resolve_actor_identity(context, organization_id),
            actor_display=context.user.full_name or context.user.email,
        )
        self.event_delivery_dispatcher.enqueue_immediate(deliveries)
        return McpSignInResult(mcp_server_id=server.id, agent_id=agent_id)

    def sign_out(
        self, organization_id: UUID, server_id: UUID, agent_id: UUID | None, context: CurrentUserContext
    ) -> None:
        """Forgets the Organization's sign-in, or an Agent's own credential of either kind."""
        server, agent = self._authorize(organization_id, server_id, agent_id, context)
        deliveries = self.repository.delete_credential_with_event(
            server,
            agent,
            actor=resolve_actor_identity(context, organization_id),
            actor_display=context.user.full_name or context.user.email,
        )
        self.event_delivery_dispatcher.enqueue_immediate(deliveries)

    def callback_page(self, code: str | None, state: str | None, error: str | None) -> HTMLResponse:
        """Posts the result to the web app on its own origin and closes the popup.

        It posts twice: on a BroadcastChannel, which reaches the app's tab even when the
        authorization server's `Cross-Origin-Opener-Policy` severed the popup from it, and to
        `window.opener` where there still is one. Either way the app completes the sign-in
        through its authenticated request, so the session check stays.

        Unauthenticated, so it checks only the state's signature; the opener's authenticated
        completion checks everything else.
        """
        valid = state is not None and self._state(state) is not None
        if error or not code or not valid:
            message: dict = {"type": MESSAGE_TYPE, "error": (error or "The sign-in did not return a code.")[:200]}
            if valid:
                # The app's channel listener is pinned to its sign-in's state; without it an
                # error relayed over the channel would be dropped and the app would wait on.
                message["state"] = state
            blurb = "The sign-in did not complete. You can close this window."
        else:
            message = {"type": MESSAGE_TYPE, "code": code, "state": state}
            blurb = "Signed in. You can close this window."

        def script_safe(value: object) -> str:
            return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

        origin = self.config.web_app_url.rstrip("/")
        html = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>MCP server sign-in</title></head>
<body style="font-family: system-ui, -apple-system, sans-serif; padding: 24px; color: #333;">
<p>{blurb}</p>
<script>
  (function () {{
    var msg = {script_safe(message)};
    // Some authorization servers send Cross-Origin-Opener-Policy: same-origin, which leaves
    // this page without an opener. The channel still reaches the app's tab on this origin.
    try {{ var channel = new BroadcastChannel({script_safe(MESSAGE_TYPE)}); channel.postMessage(msg); channel.close(); }} catch (e) {{}}
    if (window.opener) {{ window.opener.postMessage(msg, {script_safe(origin)}); }}
    window.close();
  }})();
</script>
</body>
</html>"""
        return HTMLResponse(content=html)
