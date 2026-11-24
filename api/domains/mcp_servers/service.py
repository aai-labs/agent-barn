import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError

from api.core.config import Config
from api.domains.agents.models import Agent
from api.domains.auth.models import CurrentUserContext
from api.domains.custom_api.request import RequestRefused, credential_headers
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.mcp_servers import oauth
from api.domains.mcp_servers.broker import CredentialUnavailable, McpCredentialBroker, is_oauth
from api.domains.mcp_servers.models import (
    AgentMcpServerCreate,
    AgentMcpServerUpdate,
    McpCredentialStatus,
    McpHeaderInput,
    McpHeaderRead,
    McpServerCreate,
    McpServerProbeRead,
    McpServerProbeRequest,
    McpServerRead,
    McpServerScope,
    McpServerUpdate,
    McpSignInRead,
    OrganizationMcpServer,
    derive_identifier,
)
from api.domains.mcp_servers.probe import McpProbeError, McpServerProbe, ProbeResult, ToolAnalysis, analyse_tools
from api.domains.mcp_servers.repository import McpServerRepository, McpServerUsage
from api.domains.mcp_servers.sign_in import redirect_uri
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.crypto import decrypt_token, encrypt_token

_MANAGE_DENIED = "Only Organization Owners and Admins can manage MCP servers."
_NOT_FOUND = "MCP server not found"


def _identifier_taken(identifier: str, use: str | None = None) -> HTTPException:
    where = {
        "organization": "an Organization MCP server",
        "agent": "an Agent's own MCP server",
    }.get(use or "", "another MCP server")
    return HTTPException(
        status.HTTP_409_CONFLICT,
        f'This name produces the identifier "{identifier}", which {where} uses. Choose another name.',
    )


@dataclass
class _Draft:
    """A server's settings after applying an update, before anything is saved."""

    fields: dict[str, Any]
    config: dict
    changed: list[str]
    reaches_server: bool


@inject
@singleton
@dataclass
class McpServerService:
    """Organization MCP Servers: an Organization's remote MCP servers and their one credential.

    Reading the list needs only `organization.read`; everything that can change what Agents
    reach, or reveal how they reach it, needs `mcp_server.manage`.

    The underscored `_create`, `_update`, `_delete` and probe methods are shared with Agent
    MCP Servers, whose service authorizes the caller against the Agent before using them.
    """

    repository: McpServerRepository
    probe_client: McpServerProbe
    permission_policy: PermissionPolicy
    event_delivery_dispatcher: EventDeliveryDispatcher
    broker: McpCredentialBroker
    config: Config

    # --- reads -------------------------------------------------------------

    def list_servers(self, organization_id: UUID, context: CurrentUserContext) -> list[McpServerRead]:
        self.permission_policy.require(context, organization_id, PermissionKey.ORGANIZATION_READ)
        manager = self._is_manager(context, organization_id)
        usage = self.repository.usage(organization_id)
        return [
            self._read(server, usage.get(server.id), manager=manager)
            for server in self.repository.list_for_organization(organization_id)
        ]

    def get_server(self, organization_id: UUID, server_id: UUID, context: CurrentUserContext) -> McpServerRead:
        self.permission_policy.require(context, organization_id, PermissionKey.ORGANIZATION_READ)
        server = self._find(organization_id, server_id)
        return self._read(
            server,
            self.repository.usage(organization_id).get(server.id),
            manager=self._is_manager(context, organization_id),
        )

    # --- writes ------------------------------------------------------------

    def create_server(self, organization_id: UUID, data: McpServerCreate, context: CurrentUserContext) -> McpServerRead:
        self._require_manage(context, organization_id)
        return self._create(organization_id, data, context, agent=None)

    def _create(
        self,
        organization_id: UUID,
        data: AgentMcpServerCreate,
        context: CurrentUserContext,
        *,
        agent: Agent | None,
    ) -> McpServerRead:
        identifier = data.identifier
        use = self.repository.identifier_use(organization_id, identifier, agent.id if agent else None)
        if use is not None:
            raise _identifier_taken(identifier, use)
        config = {
            "auth": data.auth.model_dump(exclude_none=True),
            "headers": [_header(h, None) for h in data.headers],
        }
        if is_oauth(config):
            # Nothing can be probed before someone signs in, so saving checks the sign-in setup.
            config["auth"], _ = self._oauth_auth(data.url, config["auth"], None, url_changed=True)
        else:
            self._verify(identifier, data.url, config, data.tool_include, data.tool_exclude)
        server = OrganizationMcpServer(
            organization_id=organization_id,
            agent_id=agent.id if agent else None,
            identifier=identifier,
            name=data.name,
            description=data.description,
            url=data.url,
            scope=McpServerScope.AGENT.value if agent else getattr(data, "scope", McpServerScope.SELECTED_AGENTS).value,
            enabled=data.enabled,
            restricted=False if agent else bool(getattr(data, "restricted", False)),
            credentials_encrypted=self._encrypt(config),
            tool_include=data.tool_include,
            tool_exclude=data.tool_exclude,
            created_by_user_id=context.user.id,
        )
        try:
            self._save(server, "created", config, [], context)
        except IntegrityError:
            raise _identifier_taken(identifier) from None
        return self._read(server, McpServerUsage(0, 0), manager=True, agent_name=agent.name if agent else None)

    def update_server(
        self, organization_id: UUID, server_id: UUID, data: McpServerUpdate, context: CurrentUserContext
    ) -> McpServerRead:
        self._require_manage(context, organization_id)
        server = self._find(organization_id, server_id)
        self._update(server, data, context)
        return self._read(server, self.repository.usage(organization_id).get(server.id), manager=True)

    def _update(self, server: OrganizationMcpServer, data: AgentMcpServerUpdate, context: CurrentUserContext) -> None:
        draft = self._draft(server, data)
        previous_auth = self._credentials(server)["auth"]
        url_changed = "url" in draft.changed
        clear: frozenset[str] = frozenset()
        reconfigured = False
        release_hold: UUID | None = None
        if is_oauth(draft.config):
            submitted = data.auth.model_dump(exclude_none=True) if data.auth is not None else {"type": "oauth"}
            draft.config["auth"], reconfigured = self._oauth_auth(
                draft.fields["url"], submitted, previous_auth, url_changed=url_changed
            )
            if reconfigured:
                # Every sign-in was made with the old client or for the old URL, and a token is
                # no credential for an OAuth server.
                clear = frozenset({"oauth", "static"})
                draft.changed = [*dict.fromkeys([*draft.changed, "auth"])]
            elif "auth" in draft.changed and draft.config["auth"] == previous_auth:
                draft.changed.remove("auth")
        elif url_changed or previous_auth.get("type") == "oauth":
            clear = frozenset({"oauth"})
        if draft.changed:
            if draft.reaches_server and not is_oauth(draft.config):
                self._verify(
                    server.identifier,
                    draft.fields["url"],
                    draft.config,
                    draft.fields["tool_include"],
                    draft.fields["tool_exclude"],
                )
            elif (
                draft.reaches_server
                and not reconfigured
                and (held := self.repository.credential(server.id, server.agent_id))
            ):
                # A signed-in OAuth server is checked with its own sign-in, so a tool filter
                # change can't expose tools whose OpenClaw names collide. Before any sign-in
                # there is nothing to connect with, and nothing for Agents to use either.
                self._verify(
                    server.identifier,
                    draft.fields["url"],
                    self._probe_config(server, draft.config),
                    draft.fields["tool_include"],
                    draft.fields["tool_exclude"],
                )
                # The filter now passes with this sign-in, so a sign-in held back for colliding
                # tool names becomes usable once the change is saved.
                release_hold = held.id
            for name, value in draft.fields.items():
                setattr(server, name, value)
            server.credentials_encrypted = self._encrypt(draft.config)
            self._save(server, "updated", draft.config, draft.changed, context, clear=clear)
            if release_hold is not None:
                self.repository.clear_tool_filter_hold(release_hold)

    def delete_server(self, organization_id: UUID, server_id: UUID, context: CurrentUserContext) -> None:
        """Deleting removes the server's attachments with it; Agents lose it at the gateway at once."""
        self._require_manage(context, organization_id)
        self._delete(self._find(organization_id, server_id), context)

    def _delete(self, server: OrganizationMcpServer, context: CurrentUserContext) -> None:
        self._save(server, "deleted", self._credentials(server), [], context)

    # --- probing -----------------------------------------------------------

    def probe_new(
        self, organization_id: UUID, data: McpServerProbeRequest, context: CurrentUserContext
    ) -> McpServerProbeRead:
        self._require_manage(context, organization_id)
        return self._probe_new(data, agent=False)

    def _probe_new(self, data: McpServerProbeRequest, *, agent: bool) -> McpServerProbeRead:
        config = {"auth": data.auth.model_dump(exclude_none=True), "headers": [_header(h, None) for h in data.headers]}
        if is_oauth(config):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Save the server and sign the Agent in, then test it."
                if agent
                else "Save the server and sign in for the Organization, then test it.",
            )
        identifier = derive_identifier(data.name or "") or "server"
        result = self._probe(data.url, config)
        return _probe_read(result, analyse_tools(identifier, result, None, None))

    def probe_saved(
        self,
        organization_id: UUID,
        server_id: UUID,
        data: McpServerUpdate | None,
        context: CurrentUserContext,
    ) -> McpServerProbeRead:
        """Probe the saved server, or what it would be with `data` applied; nothing is saved."""
        self._require_manage(context, organization_id)
        return self._probe_saved(self._find(organization_id, server_id), data)

    def _probe_saved(self, server: OrganizationMcpServer, data: AgentMcpServerUpdate | None) -> McpServerProbeRead:
        draft = self._draft(server, data or AgentMcpServerUpdate())
        result = self._probe(draft.fields["url"], self._probe_config(server, draft.config))
        analysis = analyse_tools(server.identifier, result, draft.fields["tool_include"], draft.fields["tool_exclude"])
        return _probe_read(result, analysis)

    # --- helpers -----------------------------------------------------------

    def _is_manager(self, context: CurrentUserContext, organization_id: UUID) -> bool:
        return self.permission_policy.resolve(context, organization_id, PermissionKey.MCP_SERVER_MANAGE) is not None

    def _require_manage(self, context: CurrentUserContext, organization_id: UUID) -> None:
        # Resolving organization.read first keeps a caller from another Organization on the
        # same 403 every Organization route gives, before the manage check can differ.
        self.permission_policy.require(context, organization_id, PermissionKey.ORGANIZATION_READ)
        self.permission_policy.require(context, organization_id, PermissionKey.MCP_SERVER_MANAGE, detail=_MANAGE_DENIED)

    def _find(self, organization_id: UUID, server_id: UUID) -> OrganizationMcpServer:
        """An Organization server; an Agent server is reached only through its Agent."""
        server = self.repository.get(organization_id, server_id)
        if server is None or server.agent_id is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_FOUND)
        return server

    def _credentials(self, server: OrganizationMcpServer) -> dict:
        return json.loads(decrypt_token(server.credentials_encrypted, self.config.agent_token_encryption_key))

    def _encrypt(self, config: dict) -> str:
        return encrypt_token(json.dumps(config), self.config.agent_token_encryption_key)

    def _draft(self, server: OrganizationMcpServer, data: AgentMcpServerUpdate) -> _Draft:
        given = data.model_fields_set
        for name in ("name", "url", "scope", "enabled", "restricted"):
            if name in given and getattr(data, name) is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{name} cannot be null")
        # Only an Organization server's update carries these; an Agent server keeps its own.
        scope = getattr(data, "scope", None)
        restricted = getattr(data, "restricted", None)
        fields: dict[str, Any] = {
            "name": data.name.strip() if "name" in given and data.name else server.name,
            "description": data.description if "description" in given else server.description,
            "url": data.url if "url" in given else server.url,
            "scope": scope.value if "scope" in given and scope else server.scope,
            "enabled": data.enabled if "enabled" in given else server.enabled,
            "restricted": restricted if "restricted" in given and restricted is not None else server.restricted,
            "tool_include": server.tool_include,
            "tool_exclude": server.tool_exclude,
        }
        # Either filter field replaces the whole filter, so switching from an exclude list
        # to an include list needs only the new list.
        if "tool_include" in given or "tool_exclude" in given:
            fields["tool_include"] = data.tool_include
            fields["tool_exclude"] = data.tool_exclude
        previous = self._credentials(server)
        config = {"auth": previous["auth"], "headers": previous["headers"]}
        if "auth" in given and data.auth is not None:
            config["auth"] = _merged_auth(previous["auth"], data.auth.model_dump(exclude_none=True))
        if "headers" in given and data.headers is not None:
            saved = {h["name"].lower(): h for h in previous["headers"]}
            config["headers"] = [_header(h, saved.get(h.name.lower())) for h in data.headers]
        changed = [
            name
            for name in ("name", "description", "url", "scope", "enabled", "restricted")
            if fields[name] != getattr(server, name)
        ]
        if (fields["tool_include"], fields["tool_exclude"]) != (server.tool_include, server.tool_exclude):
            changed.append("tool_filter")
        if config["auth"] != previous["auth"]:
            changed.append("auth")
        if config["headers"] != previous["headers"]:
            changed.append("headers")
        reaches_server = bool({"url", "auth", "headers", "tool_filter"} & set(changed))
        return _Draft(fields=fields, config=config, changed=changed, reaches_server=reaches_server)

    def _oauth_auth(self, url: str, submitted: dict, previous: dict | None, *, url_changed: bool) -> tuple[dict, bool]:
        """The OAuth client to sign in with, registered or entered, and whether it changed.

        An existing registration is kept unless the URL, the client or the scope changes, so
        ordinary edits leave every sign-in in place.
        """
        kept = previous is not None and previous.get("type") == "oauth" and not url_changed
        if (
            kept
            and previous is not None
            and submitted.get("client_id") in (None, previous.get("client_id"))
            and submitted.get("client_secret") is None
            and submitted.get("scope") in (None, previous.get("scope"))
        ):
            return previous, False
        try:
            metadata = oauth.discover(url)
            manual_id = submitted.get("client_id") or (
                previous.get("client_id") if kept and previous and previous.get("registered") is False else None
            )
            if manual_id:
                secret = submitted.get("client_secret") or (
                    previous.get("client_secret") if previous and previous.get("client_id") == manual_id else None
                )
                client = oauth.OAuthClient(manual_id, secret, "client_secret_post" if secret else "none")
            else:
                client = oauth.register(metadata, redirect_uri(self.config))
        except oauth.OAuthError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"OAuth sign-in cannot be set up: {exc}") from None
        return {
            "type": "oauth",
            "resource": metadata.resource,
            "issuer": metadata.issuer,
            "authorization_endpoint": metadata.authorization_endpoint,
            "token_endpoint": metadata.token_endpoint,
            "scope": submitted.get("scope") or metadata.scope,
            "client_id": client.client_id,
            "client_secret": client.client_secret,
            "token_endpoint_auth_method": client.token_endpoint_auth_method,
            "registered": not manual_id,
        }, True

    def _probe_config(self, server: OrganizationMcpServer, config: dict) -> dict:
        """A token-based server probes with its own credential; an OAuth one with its own
        sign-in, the Organization's or, for an Agent server, its Agent's, which it needs first."""
        if not is_oauth(config):
            return config
        held = self.repository.credential(server.id, server.agent_id)
        if held is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Sign the Agent in to test this server."
                if server.agent_id
                else "Sign in for the Organization to test this server.",
            )
        try:
            token = self.broker.access_token(held.id, config, for_management=True)
        except CredentialUnavailable as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
        return {"auth": {"type": "bearer", "token": token}, "headers": config.get("headers", [])}

    def _sign_in(self, server: OrganizationMcpServer) -> McpSignInRead:
        held = self.repository.credential(server.id, server.agent_id)
        if held is None:
            return McpSignInRead(status="not_signed_in")
        if held.status == McpCredentialStatus.NEEDS_SIGN_IN.value:
            return McpSignInRead(status="needs_sign_in", signed_in_at=held.updated_at)
        if held.status == McpCredentialStatus.NEEDS_TOOL_FILTER.value:
            return McpSignInRead(status="needs_tool_filter", signed_in_at=held.updated_at)
        return McpSignInRead(status="signed_in", signed_in_at=held.updated_at)

    def check_connection(self, url: str, config: dict) -> ProbeResult:
        """Probes a token-based credential, mapping failures to HTTP errors."""
        return self._probe(url, config)

    def _probe(self, url: str, config: dict) -> ProbeResult:
        try:
            # Checked here as well as in the probe, so a missing token is a shape error
            # whatever stands behind the probe.
            credential_headers(config)
            return self.probe_client.probe(url, config)
        except RequestRefused as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        except KeyError, TypeError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "The authentication or headers are incomplete."
            ) from None
        except McpProbeError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"The MCP server could not be used: {exc}") from None

    def _verify(
        self, identifier: str, url: str, config: dict, include: list[str] | None, exclude: list[str] | None
    ) -> None:
        """Saving connects to the server once, so a wrong URL or key fails here, not in an Agent."""
        analysis = analyse_tools(identifier, self._probe(url, config), include, exclude)
        if analysis.collisions:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Several tools would share these OpenClaw names; hide all but one of each with the tool filter: "
                + ", ".join(analysis.collisions),
            )

    def _save(
        self,
        server: OrganizationMcpServer,
        operation: str,
        config: dict,
        changed: list[str],
        context: CurrentUserContext,
        *,
        clear: frozenset[str] = frozenset(),
    ) -> None:
        delivery_ids = self.repository.save_with_event(
            server,
            operation,
            auth_type=config["auth"]["type"],
            changed_fields=changed,
            actor=resolve_actor_identity(context, server.organization_id),
            actor_display=context.user.full_name or context.user.email,
            clear_credential_kinds=clear,
        )
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)

    def _read(
        self,
        server: OrganizationMcpServer,
        usage: McpServerUsage | None,
        *,
        manager: bool,
        agent_name: str | None = None,
    ) -> McpServerRead:
        """`manager` shows the URL and authentication shape: for an Organization server to
        `mcp_server.manage`, for an Agent server to whoever may edit it."""
        if usage is None:
            usage = McpServerUsage(1, 1) if server.agent_id else McpServerUsage(0, 0)
        read = McpServerRead(
            id=server.id,
            identifier=server.identifier,
            name=server.name,
            description=server.description,
            scope=server.scope,
            enabled=server.enabled,
            restricted=server.restricted,
            agent_id=server.agent_id,
            agent_name=agent_name,
            tool_include=server.tool_include,
            tool_exclude=server.tool_exclude,
            attachment_count=usage.attachment_count,
            agent_count=usage.agent_count,
            created_at=server.created_at,
            updated_at=server.updated_at,
        )
        config = self._credentials(server)
        if is_oauth(config):
            read.sign_in = self._sign_in(server)
        if manager:
            read.url = server.url
            read.auth_type = config["auth"]["type"]
            read.auth_header_name = config["auth"].get("header_name")
            read.headers = [
                McpHeaderRead(name=h["name"], secret=h["secret"], value=None if h["secret"] else h["value"])
                for h in config["headers"]
            ]
            if is_oauth(config):
                read.oauth_client_id = config["auth"].get("client_id")
                read.oauth_registered = bool(config["auth"].get("registered"))
        return read


def _merged_auth(previous: dict, submitted: dict) -> dict:
    """A saved token carries over only to the same scheme sent in the same header."""
    same_place = submitted["type"] == previous["type"] and (
        submitted["type"] != "api_key"
        or (submitted.get("header_name") or "").lower() == (previous.get("header_name") or "").lower()
    )
    return {**previous, **submitted} if same_place else submitted


def _header(submitted: McpHeaderInput, saved: dict | None) -> dict:
    """A secret header sent without a value keeps the saved secret of the same name."""
    value = submitted.value
    if value is None and submitted.secret and saved is not None and saved["secret"]:
        value = saved["value"]
    return {"name": submitted.name, "value": value, "secret": submitted.secret}


def _probe_read(result: ProbeResult, analysis: ToolAnalysis) -> McpServerProbeRead:
    return McpServerProbeRead(
        server_name=result.server_name,
        server_version=result.server_version,
        protocol_version=result.protocol_version,
        tools=analysis.tools,
        warnings=analysis.warnings,
    )
