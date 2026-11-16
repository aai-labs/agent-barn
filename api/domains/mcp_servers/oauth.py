"""OAuth for MCP servers, as MCP's authorization spec describes it, with nothing kept in a pod.

- Discovery: the server's 401 challenge names its protected-resource metadata (RFC 9728),
  which names the authorization server, whose metadata (RFC 8414, or OpenID discovery) gives
  the endpoints.
- Registration: dynamic client registration (RFC 7591) where the server offers it, or a
  client an Admin registered by hand.
- Sign-in: authorization code with PKCE (S256) and the `resource` parameter (RFC 8707).
- Refresh: the gateway's job, through `refresh`.

Every request goes to a public HTTPS address, pinned after the check, with no redirects:
the same policy as the MCP server itself, since every URL here comes from a server an Admin
chose or from metadata that server published.
"""

import base64
import http.client
import json
import time
import urllib.parse
from dataclasses import dataclass, field

from api.domains.custom_api.request import PinnedHTTPSConnection, RequestRefused, parse_url, public_addresses

TIMEOUT_SECONDS = 15
MAX_BYTES = 1024 * 1024
DEFAULT_TOKEN_LIFETIME = 3600
MAX_TOKEN_LIFETIME = 24 * 3600
USER_AGENT = "agent-barn-mcp-oauth/1"
CLIENT_NAME = "Agent Barn"
PROTOCOL_VERSION = "2025-11-25"


class OAuthError(Exception):
    """The server's OAuth setup cannot be used. The message is shown to an Admin."""


class OAuthRefused(OAuthError):
    """The authorization server refused the grant: someone has to sign in again."""


@dataclass(frozen=True)
class _Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict:
        try:
            value = json.loads(self.body.decode("utf-8", errors="replace"))
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}


def _request(method: str, url: str, *, body: bytes | None = None, headers: dict[str, str] | None = None) -> _Response:
    try:
        parsed = parse_url(url)
        port = parsed.port or 443
        address = public_addresses(parsed.hostname, port)[0]
    except RequestRefused as exc:
        raise OAuthError(f"{_host(url)} is not a public HTTPS address: {exc}") from None
    path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    connection = PinnedHTTPSConnection(parsed.hostname, address, port, timeout=TIMEOUT_SECONDS)
    try:
        connection.request(method, path, body=body, headers={"user-agent": USER_AGENT, **(headers or {})})
        response = connection.getresponse()
        content = response.read(MAX_BYTES + 1)
        received = {name.lower(): value for name, value in response.getheaders()}
    except (OSError, http.client.HTTPException) as exc:
        raise OAuthError(f"{_host(url)} could not be reached.") from exc
    finally:
        connection.close()
    if len(content) > MAX_BYTES:
        raise OAuthError(f"{_host(url)} answered with more than 1 MiB.")
    return _Response(response.status, received, content)


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or url


def _form(values: dict[str, str | None]) -> bytes:
    return urllib.parse.urlencode({k: v for k, v in values.items() if v is not None}).encode()


def _challenge(header: str) -> dict[str, str]:
    import re

    if not header.lower().startswith("bearer"):
        return {}
    return {name.lower(): value for name, value in re.findall(r'([A-Za-z_]+)="([^"]*)"', header)}


# --- discovery -------------------------------------------------------------------


@dataclass(frozen=True)
class OAuthMetadata:
    """What signing in to one MCP server needs, discovered from the server itself."""

    resource: str
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None
    scope: str | None
    token_endpoint_auth_methods: list[str] = field(default_factory=list)


def _well_known(base: str, suffix: str) -> list[str]:
    """RFC 8414 / RFC 9728 well-known locations for `base`, path-aware first."""
    parts = urllib.parse.urlsplit(base)
    origin = f"{parts.scheme}://{parts.netloc}"
    path = parts.path.rstrip("/")
    urls = [f"{origin}/.well-known/{suffix}{path}"] if path else []
    urls.append(f"{origin}/.well-known/{suffix}")
    return urls


def _first_json(urls: list[str], required: tuple[str, ...]) -> dict | None:
    for url in urls:
        response = _request("GET", url, headers={"accept": "application/json"})
        if response.status == 200:
            data = response.json()
            if all(isinstance(data.get(key), str) and data.get(key) for key in required):
                return data
    return None


def discover(server_url: str) -> OAuthMetadata:
    """Follows the server's own pointers to its authorization server."""
    initialize = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "agent-barn"}},
        }
    ).encode()
    answer = _request(
        "POST",
        server_url,
        body=initialize,
        headers={"content-type": "application/json", "accept": "application/json, text/event-stream"},
    )
    if 200 <= answer.status < 300:
        raise OAuthError("This server does not ask for a sign-in; choose another authentication.")
    challenge = _challenge(answer.headers.get("www-authenticate", ""))
    if answer.status != 401:
        raise OAuthError(f"The server did not ask for a sign-in (HTTP {answer.status}).")
    resource_urls = [challenge["resource_metadata"]] if "resource_metadata" in challenge else []
    resource_urls += _well_known(server_url, "oauth-protected-resource")
    resource_metadata = _first_json(resource_urls, ())
    authorization_servers = (resource_metadata or {}).get("authorization_servers")
    if isinstance(authorization_servers, list) and authorization_servers and isinstance(authorization_servers[0], str):
        issuer = authorization_servers[0]
    else:
        # Servers from before MCP adopted RFC 9728 act as their own authorization server.
        parts = urllib.parse.urlsplit(server_url)
        issuer = f"{parts.scheme}://{parts.netloc}"
    metadata = _first_json(
        _well_known(issuer, "oauth-authorization-server")
        + _well_known(issuer, "openid-configuration")
        + [issuer.rstrip("/") + "/.well-known/openid-configuration"],
        ("authorization_endpoint", "token_endpoint"),
    )
    if metadata is None:
        raise OAuthError(f"{_host(issuer)} publishes no OAuth authorization-server metadata.")
    if str(metadata.get("issuer", issuer)).rstrip("/") != issuer.rstrip("/"):
        # RFC 8414 section 3.3: metadata naming another issuer must not be used.
        raise OAuthError("The authorization server's metadata names a different issuer.")
    methods = metadata.get("code_challenge_methods_supported")
    if isinstance(methods, list) and "S256" not in methods:
        raise OAuthError("The authorization server does not support PKCE with S256, which sign-in requires.")
    scopes = challenge.get("scope")
    supported_scopes = (resource_metadata or {}).get("scopes_supported")
    if not scopes and isinstance(supported_scopes, list):
        scopes = " ".join(str(s) for s in supported_scopes) or None
    auth_methods = metadata.get("token_endpoint_auth_methods_supported")
    registration = metadata.get("registration_endpoint")
    return OAuthMetadata(
        resource=str((resource_metadata or {}).get("resource") or server_url),
        issuer=issuer,
        authorization_endpoint=metadata["authorization_endpoint"],
        token_endpoint=metadata["token_endpoint"],
        registration_endpoint=registration if isinstance(registration, str) and registration else None,
        scope=scopes,
        token_endpoint_auth_methods=[str(m) for m in auth_methods] if isinstance(auth_methods, list) else [],
    )


# --- registration ----------------------------------------------------------------


@dataclass(frozen=True)
class OAuthClient:
    client_id: str
    client_secret: str | None
    token_endpoint_auth_method: str


def register(metadata: OAuthMetadata, redirect_uri: str) -> OAuthClient:
    """Registers Agent Barn as a client (RFC 7591), public where the server allows it."""
    if metadata.registration_endpoint is None:
        raise OAuthError(
            "This server does not support automatic client registration. Register an OAuth app with it "
            "and enter its client ID (and secret) instead."
        )
    supported = metadata.token_endpoint_auth_methods or ["client_secret_basic"]
    method = next(
        (m for m in ("none", "client_secret_basic", "client_secret_post") if m in supported),
        "client_secret_basic",
    )
    request = {
        "client_name": CLIENT_NAME,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": method,
    }
    if metadata.scope:
        request["scope"] = metadata.scope
    response = _request(
        "POST",
        metadata.registration_endpoint,
        body=json.dumps(request).encode(),
        headers={"content-type": "application/json", "accept": "application/json"},
    )
    data = response.json()
    client_id = data.get("client_id")
    if response.status not in {200, 201} or not isinstance(client_id, str) or not client_id:
        reason = data.get("error_description") or data.get("error") or f"HTTP {response.status}"
        raise OAuthError(f"Automatic client registration failed: {str(reason)[:200]}")
    secret = data.get("client_secret")
    return OAuthClient(
        client_id=client_id,
        client_secret=secret if isinstance(secret, str) and secret else None,
        token_endpoint_auth_method=str(data.get("token_endpoint_auth_method") or method),
    )


# --- sign-in and refresh ----------------------------------------------------------


def authorize_url(config: dict, *, state: str, code_challenge: str, redirect_uri: str) -> str:
    query = {
        "response_type": "code",
        "client_id": config["client_id"],
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "resource": config["resource"],
    }
    if config.get("scope"):
        query["scope"] = config["scope"]
    endpoint = config["authorization_endpoint"]
    separator = "&" if urllib.parse.urlsplit(endpoint).query else "?"
    return endpoint + separator + urllib.parse.urlencode(query)


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: float
    scope: str | None

    def as_grant(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scope": self.scope,
        }


def _token_request(config: dict, values: dict[str, str | None]) -> TokenSet:
    headers = {"content-type": "application/x-www-form-urlencoded", "accept": "application/json"}
    method = config.get("token_endpoint_auth_method") or "none"
    values = {**values, "resource": config["resource"]}
    if method == "client_secret_basic" and config.get("client_secret"):
        pair = (
            f"{urllib.parse.quote(config['client_id'], safe='')}:{urllib.parse.quote(config['client_secret'], safe='')}"
        )
        headers["authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
    else:
        values["client_id"] = config["client_id"]
        if method == "client_secret_post" or (method != "none" and config.get("client_secret")):
            values["client_secret"] = config.get("client_secret")
    response = _request("POST", config["token_endpoint"], body=_form(values), headers=headers)
    data = response.json()
    if response.status in {400, 401} and data.get("error") in {
        "invalid_grant",
        "invalid_client",
        "unauthorized_client",
    }:
        raise OAuthRefused(str(data.get("error_description") or data["error"])[:200])
    token = data.get("access_token")
    if response.status != 200 or not isinstance(token, str) or not token:
        reason = data.get("error_description") or data.get("error") or f"HTTP {response.status}"
        raise OAuthError(f"The token endpoint refused the request: {str(reason)[:200]}")
    if any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise OAuthError("The token endpoint issued an unusable access token.")
    try:
        lifetime = int(data.get("expires_in", DEFAULT_TOKEN_LIFETIME))
    except TypeError, ValueError, OverflowError:
        lifetime = DEFAULT_TOKEN_LIFETIME
    refresh = data.get("refresh_token")
    return TokenSet(
        access_token=token,
        refresh_token=refresh if isinstance(refresh, str) and refresh else None,
        expires_at=time.time() + max(0, min(lifetime, MAX_TOKEN_LIFETIME)),
        scope=data.get("scope") if isinstance(data.get("scope"), str) else None,
    )


def exchange_code(config: dict, *, code: str, code_verifier: str, redirect_uri: str) -> TokenSet:
    return _token_request(
        config,
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        },
    )


def refresh(config: dict, refresh_token: str) -> TokenSet:
    """Raises `OAuthRefused` when the grant is gone, `OAuthError` when the server is unusable."""
    tokens = _token_request(config, {"grant_type": "refresh_token", "refresh_token": refresh_token})
    # A server that does not rotate keeps the refresh token it was sent (RFC 6749 section 6).
    return (
        tokens
        if tokens.refresh_token
        else TokenSet(tokens.access_token, refresh_token, tokens.expires_at, tokens.scope)
    )
