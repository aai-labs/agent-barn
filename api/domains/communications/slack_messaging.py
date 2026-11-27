"""Agent Barn's own Slack messages, sent through an Agent's Slack Connection.

These are not the Agent's conversation: the Agent never sees them and they ignore the
Connection's channel and direct-message policies. The bot token stays in this domain;
callers name a Connection and get back only Slack identifiers.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.auth.models import CurrentUserContext
from api.domains.communications.models import (
    CommunicationConnection,
    SlackWorkspaceConnectionRead,
    SlackWorkspaceRead,
)
from api.domains.communications.plugins.slack import SlackPlatformPlugin
from api.domains.communications.repository import CommunicationConnectionRepository
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.shared.cache import cached
from api.infrastructure.slack.client import SlackClient

logger = logging.getLogger(__name__)

# auth.test answers the same for a token until its app is reinstalled elsewhere.
WORKSPACE_CACHE_SECONDS = 600


@singleton
class SlackClients:
    """Builds the Slack Web API client for a Connection's bot token; tests replace it."""

    def for_connection(self, bot_token: str, api_url: str | None) -> SlackClient:
        return SlackClient(bot_token, api_url=api_url)


@dataclass(frozen=True)
class SlackWorkspace:
    team_id: str
    name: str


@dataclass(frozen=True)
class SlackConnectionWorkspace:
    """One enabled Slack Connection and the workspace its app is installed in."""

    connection_id: UUID
    agent_id: UUID
    agent_name: str
    workspace: SlackWorkspace


@dataclass(frozen=True)
class SlackUser:
    id: str
    label: str


@inject
@singleton
@dataclass
class SlackMessaging:
    config: Config
    repository: CommunicationConnectionRepository
    clients: SlackClients

    def _client(self, connection: CommunicationConnection) -> SlackClient:
        credentials = json.loads(
            decrypt_token(connection.credentials_encrypted, self.config.agent_token_encryption_key)
        )
        api_url = (connection.settings or {}).get("api_url") or None
        return self.clients.for_connection(credentials["bot_token"], api_url)

    def workspace(self, connection: CommunicationConnection) -> SlackWorkspace:
        """The workspace the Connection's app is installed in. Raises SlackFetchError when Slack can't say."""
        client = self._client(connection)
        # A new token or server can be another workspace's app.
        material = f"{connection.id} {connection.credentials_encrypted} {(connection.settings or {}).get('api_url')}"
        key = hashlib.sha256(material.encode()).hexdigest()

        def fetch() -> SlackWorkspace:
            found = client.get_workspace()
            return SlackWorkspace(team_id=found["team_id"], name=found["team"] or found["team_id"])

        return cached(f"slack-workspace:{key}", fetch, ttl=WORKSPACE_CACHE_SECONDS)

    def enabled_connection(self, agent_id: UUID) -> CommunicationConnection | None:
        """The Agent's own Slack Connection while it is turned on."""
        connection = self.repository.get_active_by_platform_key(agent_id, SlackPlatformPlugin.key)
        return connection if connection is not None and connection.enabled else None

    def connection(self, connection_id: UUID) -> CommunicationConnection | None:
        """A Connection that is not retired, enabled or not."""
        return self.repository.get_active(connection_id)

    def connection_workspaces(self, scope: AuthorizationScope) -> list[SlackConnectionWorkspace]:
        """Enabled Slack Connections of the Agents in scope, with their workspaces.

        A Connection whose workspace Slack would not report is left out rather than guessed.
        """
        found = []
        for connection, agent_name in self.repository.list_enabled_by_platform_in_scope(SlackPlatformPlugin.key, scope):
            try:
                workspace = self.workspace(connection)
            except Exception as exc:
                logger.warning("Slack did not report the workspace of Connection %s: %s", connection.id, exc)
                continue
            found.append(SlackConnectionWorkspace(connection.id, connection.agent_id, agent_name, workspace))
        return found

    def find_user(self, connection: CommunicationConnection, user_id: str) -> SlackUser | None:
        """An active, human member of the Connection's workspace, by Slack user ID."""
        for user in self._client(connection).list_users(user_id):
            if user["id"] == user_id:
                return SlackUser(id=user_id, label=user["display_name"] or user["real_name"] or user["name"] or user_id)
        return None

    def post_direct_message(
        self, connection: CommunicationConnection, user_id: str, text: str, blocks: list[dict]
    ) -> tuple[str, str]:
        """Opens the bot's direct message with the user and posts; returns its channel and ts."""
        client = self._client(connection)
        channel_id = client.open_dm(user_id)
        return channel_id, client.post_message(channel_id, text, blocks=blocks)

    def update_message(
        self, connection: CommunicationConnection, channel_id: str, ts: str, text: str, blocks: list[dict]
    ) -> None:
        self._client(connection).update_message(channel_id, ts, text, blocks)


@inject
@singleton
@dataclass
class SlackRecipients:
    """Who a person may choose to receive Agent Barn's own Slack direct messages.

    Only workspaces reached through an enabled Slack Connection of an Agent the person
    can update (`agent.update`) are offered, the same authority the Connection's own
    directory search needs.
    """

    authorization: AgentAuthorization
    messaging: SlackMessaging

    def _reachable(self, context: CurrentUserContext) -> list[SlackConnectionWorkspace]:
        return self.messaging.connection_workspaces(
            self.authorization.authorization_scope(context, PermissionKey.AGENT_UPDATE)
        )

    def workspaces(self, context: CurrentUserContext) -> list[SlackWorkspaceRead]:
        grouped: dict[str, SlackWorkspaceRead] = {}
        for found in self._reachable(context):
            workspace = grouped.setdefault(
                found.workspace.team_id,
                SlackWorkspaceRead(team_id=found.workspace.team_id, name=found.workspace.name, connections=[]),
            )
            workspace.connections.append(
                SlackWorkspaceConnectionRead(
                    agent_id=found.agent_id, agent_name=found.agent_name, connection_id=found.connection_id
                )
            )
        return sorted(grouped.values(), key=lambda item: (item.name.lower(), item.team_id))

    def require_user(self, context: CurrentUserContext, team_id: str, user_id: str) -> SlackUser:
        """The chosen Slack user, found in a workspace the person reaches through an Agent they can update."""
        connections = [found for found in self._reachable(context) if found.workspace.team_id == team_id]
        if not connections:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Choose a Slack user from a workspace that an Agent you can update is connected to",
            )
        for found in connections:
            connection = self.messaging.connection(found.connection_id)
            if connection is None:
                continue
            try:
                user = self.messaging.find_user(connection, user_id)
            except Exception:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Slack could not be reached; try again") from None
            if user is not None:
                return user
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That Slack user is not an active member of the workspace")
