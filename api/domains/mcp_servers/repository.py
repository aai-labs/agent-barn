from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlalchemy import and_, func, or_, true
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentStatus
from api.domains.events import ActorIdentity, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import (
    AGENT_UPDATED,
    EVENT_REGISTRY,
    ORGANIZATION_MCP_SERVER_CREATED,
    ORGANIZATION_MCP_SERVER_DELETED,
    ORGANIZATION_MCP_SERVER_UPDATED,
)
from api.domains.events.repository import OutboxMessageRepository
from api.domains.integrations.models import AgentIntegrationRuntime
from api.domains.mcp_servers.models import (
    AgentMcpGatewayToken,
    AgentMcpServerAttachment,
    McpCredentialStatus,
    McpServerCredential,
    McpServerScope,
    OrganizationMcpServer,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

#: Runtime states in which a generation's credentials are honoured, as for Custom API tokens.
_LIVE_RUNTIME_STATES = ("preparing", "provisioned", "ready", "stopping")

_EVENT_BY_OPERATION = {
    "created": ORGANIZATION_MCP_SERVER_CREATED,
    "updated": ORGANIZATION_MCP_SERVER_UPDATED,
    "deleted": ORGANIZATION_MCP_SERVER_DELETED,
}


@dataclass(frozen=True)
class McpServerUsage:
    """How many Agents a server reaches. Deleted Agents are never counted."""

    attachment_count: int
    agent_count: int


@inject
@singleton
@dataclass
class McpServerRepository:
    delegate: PostgresRepositoryDelegate
    outbox: OutboxMessageRepository

    def list_for_organization(self, organization_id: UUID) -> list[OrganizationMcpServer]:
        """The Organization's own servers, without any Agent server."""
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(OrganizationMcpServer)
                    .where(
                        OrganizationMcpServer.organization_id == organization_id,
                        col(OrganizationMcpServer.agent_id).is_(None),
                    )
                    .order_by(col(OrganizationMcpServer.identifier))
                ).all()
            )

    def list_agent_servers(self, organization_id: UUID, agent_id: UUID) -> list[tuple[OrganizationMcpServer, str]]:
        """One undeleted Agent's own servers, with its name. Callers apply user visibility; no
        query lists every Agent's, which are seen through each Agent, like its own integration
        credentials."""
        with Session(self.delegate.engine) as session:
            query = (
                select(OrganizationMcpServer, Agent.name)
                .join(
                    Agent,
                    (col(Agent.id) == col(OrganizationMcpServer.agent_id))
                    & (col(Agent.organization_id) == col(OrganizationMcpServer.organization_id)),
                )
                .where(OrganizationMcpServer.organization_id == organization_id, col(Agent.deleted_at).is_(None))
                .order_by(col(Agent.name), col(OrganizationMcpServer.identifier))
            )
            query = query.where(OrganizationMcpServer.agent_id == agent_id)
            return [(server, name) for server, name in session.exec(query).all()]

    def get(self, organization_id: UUID, server_id: UUID) -> OrganizationMcpServer | None:
        """The server, only when it belongs to `organization_id`."""
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(OrganizationMcpServer).where(
                    OrganizationMcpServer.id == server_id,
                    OrganizationMcpServer.organization_id == organization_id,
                )
            ).first()

    def identifier_use(self, organization_id: UUID, identifier: str, agent_id: UUID | None) -> str | None:
        """Whether a new server's identifier would meet another server in an Agent's runtime.

        `organization` when an Organization server has it; `agent` when an Agent server has
        it: any Agent's, for a new Organization server, since it may reach every Agent; only
        that Agent's own, for a new Agent server. A deleted Agent's servers reach no runtime,
        so they never count.
        """
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(OrganizationMcpServer.agent_id)
                .outerjoin(
                    Agent,
                    (col(Agent.id) == col(OrganizationMcpServer.agent_id))
                    & (col(Agent.organization_id) == col(OrganizationMcpServer.organization_id)),
                )
                .where(
                    OrganizationMcpServer.organization_id == organization_id,
                    OrganizationMcpServer.identifier == identifier,
                    or_(
                        col(OrganizationMcpServer.agent_id).is_(None),
                        and_(
                            col(Agent.deleted_at).is_(None),
                            true() if agent_id is None else col(OrganizationMcpServer.agent_id) == agent_id,
                        ),
                    ),
                )
            ).all()
        if any(owner is None for owner in rows):
            return "organization"
        return "agent" if rows else None

    def usage(self, organization_id: UUID) -> dict[UUID, McpServerUsage]:
        """Attachments and reachable Agents per server, counting undeleted Agents only."""
        with Session(self.delegate.engine) as session:
            attached = dict(
                session.exec(
                    select(AgentMcpServerAttachment.mcp_server_id, func.count())
                    .join(
                        Agent,
                        (col(Agent.id) == col(AgentMcpServerAttachment.agent_id))
                        & (col(Agent.organization_id) == col(AgentMcpServerAttachment.organization_id)),
                    )
                    .where(
                        AgentMcpServerAttachment.organization_id == organization_id,
                        col(Agent.deleted_at).is_(None),
                    )
                    .group_by(col(AgentMcpServerAttachment.mcp_server_id))
                ).all()
            )
            agents = session.exec(
                select(func.count())
                .select_from(Agent)
                .where(Agent.organization_id == organization_id, col(Agent.deleted_at).is_(None))
            ).one()
            servers = session.exec(
                select(OrganizationMcpServer.id, OrganizationMcpServer.scope).where(
                    OrganizationMcpServer.organization_id == organization_id,
                    col(OrganizationMcpServer.agent_id).is_(None),
                )
            ).all()
        return {
            server_id: McpServerUsage(
                attachment_count=attached.get(server_id, 0),
                agent_count=agents if scope == McpServerScope.ALL_AGENTS.value else attached.get(server_id, 0),
            )
            for server_id, scope in servers
        }

    def effective_for_agent(self, agent_id: UUID) -> list[OrganizationMcpServer]:
        """Servers this undeleted Agent may use now, from its own Organization only: its
        Organization's enabled servers for All Agents or attached to it, and its own enabled
        Agent servers.

        Identifiers are unique in the result. The services keep an Agent server off every
        Organization identifier; should both still meet, the Organization's server wins.

        Internal: the Agent start path and the gateway call it after authorizing the Agent
        by other means, so it applies no user visibility.
        """
        with Session(self.delegate.engine) as session:
            attached = (
                select(AgentMcpServerAttachment.id)
                .where(
                    AgentMcpServerAttachment.mcp_server_id == OrganizationMcpServer.id,
                    AgentMcpServerAttachment.agent_id == Agent.id,
                    AgentMcpServerAttachment.organization_id == Agent.organization_id,
                )
                .exists()
            )
            rows = session.exec(
                select(OrganizationMcpServer)
                .join(Agent, col(Agent.organization_id) == col(OrganizationMcpServer.organization_id))
                .where(
                    Agent.id == agent_id,
                    col(Agent.deleted_at).is_(None),
                    col(OrganizationMcpServer.enabled).is_(True),
                    or_(
                        and_(
                            col(OrganizationMcpServer.agent_id).is_(None),
                            or_(col(OrganizationMcpServer.scope) == McpServerScope.ALL_AGENTS.value, attached),
                        ),
                        col(OrganizationMcpServer.agent_id) == Agent.id,
                    ),
                )
                .order_by(col(OrganizationMcpServer.identifier), col(OrganizationMcpServer.agent_id).nulls_first())
            ).all()
        servers: dict[str, OrganizationMcpServer] = {}
        for server in rows:
            servers.setdefault(server.identifier, server)
        return list(servers.values())

    def save_with_event(
        self,
        server: OrganizationMcpServer,
        operation: str,
        *,
        auth_type: str,
        changed_fields: list[str],
        actor: ActorIdentity,
        actor_display: str,
        clear_credential_kinds: frozenset[str] = frozenset(),
    ) -> list[UUID]:
        """Writes or deletes the server and stages its audit Event in one commit.

        Deleting cascades the server's attachments and credentials in the database; the
        Event records how many attachments there were. `clear_credential_kinds` deletes the
        server's held credentials of those kinds in the same commit, for a change that makes
        them meaningless (another URL, client or authentication type).
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            if clear_credential_kinds and operation != "deleted":
                for row in session.exec(
                    select(McpServerCredential).where(
                        McpServerCredential.mcp_server_id == server.id,
                        col(McpServerCredential.kind).in_(sorted(clear_credential_kinds)),
                    )
                ).all():
                    session.delete(row)
            attachment_count = session.exec(
                select(func.count())
                .select_from(AgentMcpServerAttachment)
                .where(AgentMcpServerAttachment.mcp_server_id == server.id)
            ).one()
            if operation == "deleted":
                session.delete(session.merge(server))
            else:
                server.updated_at = datetime.now(UTC)
                session.add(server)
            session.flush()
            event = self._server_event(
                server,
                _EVENT_BY_OPERATION[operation],
                auth_type=auth_type,
                changed_fields=changed_fields,
                attachment_count=attachment_count,
                actor=actor,
                actor_display=actor_display,
            )
            self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return delivery_ids

    # --- Agent attachments -------------------------------------------------

    def attached_server_ids(self, agent_id: UUID) -> set[UUID]:
        with Session(self.delegate.engine) as session:
            return set(
                session.exec(
                    select(AgentMcpServerAttachment.mcp_server_id).where(AgentMcpServerAttachment.agent_id == agent_id)
                ).all()
            )

    def replace_attachments_with_event(
        self,
        agent: Agent,
        server_ids: set[UUID],
        *,
        previous: list[str],
        current: list[str],
        actor: ActorIdentity,
        actor_display: str,
    ) -> list[UUID]:
        """Makes `server_ids` the Agent's complete attachment set and stages `agent.updated`.

        The caller has checked that every id is a Selected Agents server of the Agent's own
        Organization; the composite foreign keys refuse anything else regardless.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            existing = list(
                session.exec(
                    select(AgentMcpServerAttachment).where(AgentMcpServerAttachment.agent_id == agent.id)
                ).all()
            )
            for row in existing:
                if row.mcp_server_id not in server_ids:
                    session.delete(row)
            kept = {row.mcp_server_id for row in existing}
            for server_id in server_ids - kept:
                session.add(
                    AgentMcpServerAttachment(
                        organization_id=agent.organization_id, agent_id=agent.id, mcp_server_id=server_id
                    )
                )
            session.flush()
            event = EVENT_REGISTRY.build_event(
                event_name=AGENT_UPDATED,
                schema_version=1,
                occurred_at=datetime.now(UTC),
                organization_id=agent.organization_id,
                actor=actor,
                subject=SubjectIdentity(
                    type=SubjectIdentityType.AGENT, id=agent.id, organization_id=agent.organization_id
                ),
                correlation_id=uuid4(),
                payload={
                    "organization_id": agent.organization_id,
                    "agent_id": agent.id,
                    "field_changes": {"mcp_servers": {"previous": previous, "new": current}},
                    "actor_display": actor_display,
                    "subject_display": agent.name,
                },
            )
            self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return delivery_ids

    # --- gateway credential --------------------------------------------------

    def set_gateway_token(self, agent_id: UUID, organization_id: UUID, token_hash: str, generation: UUID) -> None:
        """Replaces the Agent's MCP gateway credential with the one for `generation`."""
        with Session(self.delegate.engine) as session:
            row = session.exec(select(AgentMcpGatewayToken).where(AgentMcpGatewayToken.agent_id == agent_id)).first()
            if row is None:
                row = AgentMcpGatewayToken(
                    organization_id=organization_id, agent_id=agent_id, token_hash=token_hash, generation=generation
                )
            else:
                row.token_hash = token_hash
                row.generation = generation
                row.updated_at = datetime.now(UTC)
            session.add(row)
            session.commit()

    def authorize_gateway_token(self, token_hash: str) -> AgentMcpGatewayToken | None:
        """The token's row, only while its generation is the running Agent's current one.

        Used by the gateway, which has no user: the Agent and its Organization come from this
        row alone, never from the request.
        """
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentMcpGatewayToken)
                .join(
                    Agent,
                    (col(Agent.id) == col(AgentMcpGatewayToken.agent_id))
                    & (col(Agent.organization_id) == col(AgentMcpGatewayToken.organization_id)),
                )
                .join(AgentIntegrationRuntime, col(AgentIntegrationRuntime.agent_id) == col(Agent.id))
                .where(
                    AgentMcpGatewayToken.token_hash == token_hash,
                    col(AgentMcpGatewayToken.generation) == col(AgentIntegrationRuntime.generation),
                    col(AgentIntegrationRuntime.state).in_(_LIVE_RUNTIME_STATES),
                    Agent.status == AgentStatus.RUNNING,
                    col(Agent.deleted_at).is_(None),
                )
            ).first()

    # --- held credentials ------------------------------------------------------

    def credential(self, server_id: UUID, agent_id: UUID | None) -> McpServerCredential | None:
        """The Agent's own credential for the server, or with `agent_id` None the Organization's."""
        with Session(self.delegate.engine) as session:
            owner = (
                col(McpServerCredential.agent_id).is_(None)
                if agent_id is None
                else McpServerCredential.agent_id == agent_id
            )
            return session.exec(
                select(McpServerCredential).where(McpServerCredential.mcp_server_id == server_id, owner)
            ).first()

    def credentials_for(self, organization_id: UUID, agent_id: UUID | None) -> list[McpServerCredential]:
        """The Organization's held credentials, plus one Agent's own when `agent_id` is given."""
        with Session(self.delegate.engine) as session:
            owners = (
                col(McpServerCredential.agent_id).is_(None)
                if agent_id is None
                else or_(col(McpServerCredential.agent_id).is_(None), col(McpServerCredential.agent_id) == agent_id)
            )
            return list(
                session.exec(
                    select(McpServerCredential).where(McpServerCredential.organization_id == organization_id, owners)
                ).all()
            )

    def put_credential_with_event(
        self,
        server: OrganizationMcpServer,
        agent: Agent | None,
        *,
        kind: str,
        credentials_encrypted: str,
        user_id: UUID | None,
        actor: ActorIdentity,
        actor_display: str,
        status: str = McpCredentialStatus.ACTIVE.value,
    ) -> list[UUID]:
        """Saves the Organization's sign-in (`agent` None) or an Agent's own credential, active
        unless `status` says otherwise."""
        return self._change_credential(
            server, agent, (kind, credentials_encrypted, user_id, status), actor=actor, actor_display=actor_display
        )

    def delete_credential_with_event(
        self, server: OrganizationMcpServer, agent: Agent | None, *, actor: ActorIdentity, actor_display: str
    ) -> list[UUID]:
        return self._change_credential(server, agent, None, actor=actor, actor_display=actor_display)

    def _change_credential(
        self,
        server: OrganizationMcpServer,
        agent: Agent | None,
        replacement: tuple[str, str, UUID | None, str] | None,
        *,
        actor: ActorIdentity,
        actor_display: str,
    ) -> list[UUID]:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            owner = (
                col(McpServerCredential.agent_id).is_(None)
                if agent is None
                else McpServerCredential.agent_id == agent.id
            )
            row = session.exec(
                select(McpServerCredential)
                .where(McpServerCredential.mcp_server_id == server.id, owner)
                .with_for_update()
            ).first()
            existed = row is not None
            if replacement is None:
                if row is None:
                    return []
                session.delete(row)
            else:
                kind, encrypted, user_id, credential_status = replacement
                if row is None:
                    row = McpServerCredential(
                        organization_id=server.organization_id,
                        mcp_server_id=server.id,
                        agent_id=agent.id if agent else None,
                        kind=kind,
                        credentials_encrypted=encrypted,
                    )
                row.kind = kind
                row.credentials_encrypted = encrypted
                row.status = credential_status
                row.created_by_user_id = user_id
                row.updated_at = datetime.now(UTC)
                session.add(row)
            session.flush()
            if agent is None or server.agent_id is not None:
                # An Agent server's credential is the server's own, like the Organization's.
                event = self._server_event(
                    server,
                    ORGANIZATION_MCP_SERVER_UPDATED,
                    auth_type="oauth",
                    changed_fields=["sign_in" if replacement else "sign_out"],
                    attachment_count=0,
                    actor=actor,
                    actor_display=actor_display,
                )
            else:
                event = EVENT_REGISTRY.build_event(
                    event_name=AGENT_UPDATED,
                    schema_version=1,
                    occurred_at=datetime.now(UTC),
                    organization_id=agent.organization_id,
                    actor=actor,
                    subject=SubjectIdentity(
                        type=SubjectIdentityType.AGENT, id=agent.id, organization_id=agent.organization_id
                    ),
                    correlation_id=uuid4(),
                    payload={
                        "organization_id": agent.organization_id,
                        "agent_id": agent.id,
                        "field_changes": {
                            "mcp_server_identity." + server.identifier: {
                                "previous": "agent" if existed else "organization",
                                "new": "agent" if replacement else "organization",
                            }
                        },
                        "actor_display": actor_display,
                        "subject_display": agent.name,
                    },
                )
            self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return delivery_ids

    def _server_event(
        self,
        server: OrganizationMcpServer,
        event_name: str,
        *,
        auth_type: str,
        changed_fields: list[str],
        attachment_count: int,
        actor: ActorIdentity,
        actor_display: str,
    ):
        # An Agent server's Events are about its Agent, so they reach that Agent's audit too.
        subject = (
            SubjectIdentity(type=SubjectIdentityType.AGENT, id=server.agent_id, organization_id=server.organization_id)
            if server.agent_id is not None
            else SubjectIdentity(
                type=SubjectIdentityType.ORGANIZATION, id=server.organization_id, organization_id=server.organization_id
            )
        )
        return EVENT_REGISTRY.build_event(
            event_name=event_name,
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=server.organization_id,
            actor=actor,
            subject=subject,
            correlation_id=uuid4(),
            payload={
                "organization_id": server.organization_id,
                "mcp_server_id": server.id,
                "identifier": server.identifier,
                "url_host": urlsplit(server.url).hostname or "",
                "scope": server.scope,
                "enabled": server.enabled,
                "auth_type": auth_type,
                "changed_fields": changed_fields,
                "attachment_count": attachment_count,
                "restricted": server.restricted,
                "agent_id": server.agent_id,
                "actor_display": actor_display,
                "subject_display": server.name,
            },
        )

    def clear_tool_filter_hold(self, credential_id: UUID) -> None:
        """A credential held back for colliding tool names becomes usable (`active`)."""
        with self.locked_credential(credential_id) as row:
            if row is not None and row.status == McpCredentialStatus.NEEDS_TOOL_FILTER.value:
                row.status = McpCredentialStatus.ACTIVE.value
                row.updated_at = datetime.now(UTC)

    @contextmanager
    def locked_credential(self, credential_id: UUID) -> Iterator[McpServerCredential | None]:
        """The credential row under `FOR UPDATE`; changes made to it are committed on exit.

        Every gateway replica refreshes an OAuth grant under this lock, so one refresh token is
        never redeemed twice and a rotated one is never lost.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            row = session.exec(
                select(McpServerCredential).where(McpServerCredential.id == credential_id).with_for_update()
            ).first()
            try:
                yield row
            finally:
                # Also on the way out of an exception: marking a grant "needs sign-in" and then
                # refusing the request must keep the mark.
                if row is not None:
                    session.add(row)
                session.commit()
