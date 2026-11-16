"""Which credential an Agent's request to an Organization MCP Server is sent with.

The Agent's own credential wins; otherwise the Organization's, which for an OAuth server is
the Organization sign-in. OAuth access tokens are refreshed here, under the credential's row
lock, so every gateway replica shares one current token and a rotated refresh token is
never lost.
"""

import json
import time
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.custom_api.request import credential_headers
from api.domains.mcp_servers import oauth
from api.domains.mcp_servers.models import McpCredentialKind, McpCredentialStatus, OrganizationMcpServer
from api.domains.mcp_servers.repository import McpServerRepository
from api.infrastructure.crypto import decrypt_token, encrypt_token

#: Refresh this long before an access token expires, so none expires in flight.
REFRESH_MARGIN_SECONDS = 60

NEEDS_SIGN_IN = "This MCP server needs a sign-in before this Agent can use it."
SIGN_IN_EXPIRED = "This MCP server's sign-in has expired; it needs to be signed in again."
SIGN_IN_UNAVAILABLE = "This MCP server's sign-in service could not be reached; try again shortly."


class CredentialUnavailable(Exception):
    """No usable credential. The message is shown to the model, so it names nothing internal."""


@dataclass(frozen=True)
class ResolvedCredential:
    headers: dict[str, str]
    sensitive: list[str]
    #: The held OAuth credential whose access token was used, so a 401 can retire it.
    oauth_credential_id: UUID | None = None


def is_oauth(config: dict) -> bool:
    return config.get("auth", {}).get("type") == "oauth"


def oauth_headers(config: dict, access_token: str) -> tuple[dict[str, str], list[str]]:
    """The server's own extra headers plus the bearer token."""
    headers, sensitive = credential_headers({"auth": {"type": "none"}, "headers": config.get("headers", [])})
    headers["authorization"] = "Bearer " + access_token
    return headers, [*sensitive, access_token]


@inject
@singleton
@dataclass
class McpCredentialBroker:
    repository: McpServerRepository
    config: Config

    def _decrypt(self, value: str) -> dict:
        return json.loads(decrypt_token(value, self.config.agent_token_encryption_key))

    def server_config(self, server: OrganizationMcpServer) -> dict:
        return self._decrypt(server.credentials_encrypted)

    def resolve(self, server: OrganizationMcpServer, agent_id: UUID | None) -> ResolvedCredential:
        """Raises `CredentialUnavailable`, or `RequestRefused` for a malformed static credential."""
        config = self.server_config(server)
        own = self.repository.credential(server.id, agent_id) if agent_id else None
        if own is not None and own.kind == McpCredentialKind.STATIC.value:
            headers, sensitive = credential_headers(self._decrypt(own.credentials_encrypted))
            return ResolvedCredential(headers, sensitive)
        if own is not None or is_oauth(config):
            held = own or self.repository.credential(server.id, None)
            if held is None:
                raise CredentialUnavailable(NEEDS_SIGN_IN)
            token = self.access_token(held.id, config)
            headers, sensitive = oauth_headers(config, token)
            return ResolvedCredential(headers, sensitive, oauth_credential_id=held.id)
        headers, sensitive = credential_headers(config)
        return ResolvedCredential(headers, sensitive)

    def access_token(self, credential_id: UUID, config: dict) -> str:
        with self.repository.locked_credential(credential_id) as row:
            if row is None:
                raise CredentialUnavailable(NEEDS_SIGN_IN)
            if row.status == McpCredentialStatus.NEEDS_SIGN_IN.value:
                raise CredentialUnavailable(SIGN_IN_EXPIRED)
            grant = self._decrypt(row.credentials_encrypted)
            if grant.get("access_token") and float(grant.get("expires_at") or 0) > time.time() + REFRESH_MARGIN_SECONDS:
                return grant["access_token"]
            if not grant.get("refresh_token"):
                row.status = McpCredentialStatus.NEEDS_SIGN_IN.value
                raise CredentialUnavailable(SIGN_IN_EXPIRED)
            try:
                tokens = oauth.refresh(config["auth"], grant["refresh_token"])
            except oauth.OAuthRefused:
                row.status = McpCredentialStatus.NEEDS_SIGN_IN.value
                raise CredentialUnavailable(SIGN_IN_EXPIRED) from None
            except oauth.OAuthError:
                raise CredentialUnavailable(SIGN_IN_UNAVAILABLE) from None
            row.credentials_encrypted = encrypt_token(
                json.dumps(tokens.as_grant()), self.config.agent_token_encryption_key
            )
            return tokens.access_token

    def retire_access_token(self, credential_id: UUID) -> None:
        """The server refused the access token; the next request refreshes it."""
        with self.repository.locked_credential(credential_id) as row:
            if row is not None:
                grant = self._decrypt(row.credentials_encrypted)
                grant["expires_at"] = 0
                row.credentials_encrypted = encrypt_token(json.dumps(grant), self.config.agent_token_encryption_key)
