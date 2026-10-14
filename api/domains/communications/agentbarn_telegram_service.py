import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn
from urllib.parse import quote
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.auth.models import CurrentUserContext
from api.domains.communications.agentbarn_telegram_repository import (
    AgentBarnTelegramRepository,
    LinkTokenConsumption,
)
from api.domains.communications.models import (
    AgentBarnTelegramLinkToken,
    CommunicationConnection,
    CommunicationPlatform,
    TelegramLinkRead,
    TelegramLinkTokenCreated,
    TelegramLinkTokenRead,
    TelegramLinkTokenStatus,
)
from api.domains.communications.plugins.agentbarn_telegram import AgentBarnTelegramPlatformPlugin
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.repository import CommunicationConnectionRepository
from api.domains.rbac.catalog import PermissionKey
from api.infrastructure.crypto import decrypt_token, encrypt_token

LINK_TOKEN_TTL = timedelta(minutes=10)
# 24 random bytes encode to 32 URL-safe characters, inside Telegram's 64-character
# limit for a /start parameter.
_LINK_TOKEN_BYTES = 24
_RUNTIME_SECRET_BYTES = 32


def hash_link_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@inject
@singleton
@dataclass
class AgentBarnTelegramService:
    """Link Telegram accounts to an Agent through Agent Barn's shared bot."""

    config: Config
    authorization: AgentAuthorization
    connections: CommunicationConnectionRepository
    repository: AgentBarnTelegramRepository
    plugins: PlatformPluginRegistry

    def is_offered(self) -> bool:
        """Whether this environment has Agent Barn's own bot configured."""
        return self._plugin().is_offered()

    def runtime_secret(self, connection_id: UUID, *, create: bool) -> str | None:
        """A Connection's root secret, from which its Agent's credentials are derived.

        Starting the Agent creates it (`create=True`); the proxy and the relay only
        read it, so a Connection whose Agent never started with it has none.
        """
        key = self.config.agent_token_encryption_key
        stored = self.repository.connection_secret_encrypted(connection_id)
        if stored is None and create:
            stored = self.repository.create_connection_secret(
                connection_id, encrypt_token(secrets.token_urlsafe(_RUNTIME_SECRET_BYTES), key)
            )
        return None if stored is None else decrypt_token(stored, key)

    def create_link_token(
        self,
        agent_id: UUID,
        connection_id: UUID,
        context: CurrentUserContext,
    ) -> TelegramLinkTokenCreated:
        self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        connection = self._require_connection(context, agent_id, connection_id, PermissionKey.AGENT_UPDATE)
        plugin = self._plugin()
        if not plugin.is_offered():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{plugin.display_name} is not available",
            )
        if not connection.enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Turn this connection on before linking a Telegram account",
            )
        raw_token = secrets.token_urlsafe(_LINK_TOKEN_BYTES)
        token = self.repository.create_link_token(
            organization_id=connection.organization_id,
            agent_id=connection.agent_id,
            connection_id=connection.id,
            requested_by_membership_id=context.require_current_user_organization().id,
            token_hash=hash_link_token(raw_token),
            expires_at=datetime.now(UTC) + LINK_TOKEN_TTL,
        )
        return TelegramLinkTokenCreated(
            **self._read_token(token).model_dump(),
            url=f"https://t.me/{quote(plugin.bot_username)}?start={raw_token}",
        )

    def get_link_token(
        self,
        agent_id: UUID,
        connection_id: UUID,
        token_id: UUID,
        context: CurrentUserContext,
    ) -> TelegramLinkTokenRead:
        self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_UPDATE)
        token = self.repository.get_link_token_in_scope(token_id, connection_id, agent_id, scope)
        if token is None:
            self._raise_not_found("Telegram link")
        return self._read_token(token)

    def list_links(
        self,
        agent_id: UUID,
        connection_id: UUID,
        context: CurrentUserContext,
    ) -> list[TelegramLinkRead]:
        self.authorization.require_visible(context, agent_id)
        self._require_connection(context, agent_id, connection_id, PermissionKey.AGENT_READ)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
        return [
            TelegramLinkRead.model_validate(link)
            for link in self.repository.list_active_links_in_scope(connection_id, agent_id, scope)
        ]

    def unlink(
        self,
        agent_id: UUID,
        connection_id: UUID,
        link_id: UUID,
        context: CurrentUserContext,
    ) -> None:
        self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_UPDATE)
        if not self.repository.unlink_in_scope(link_id, connection_id, agent_id, scope, now=datetime.now(UTC)):
            self._raise_not_found("Linked Telegram account")

    def consume_link_token(
        self,
        raw_token: str,
        *,
        telegram_user_id: int,
        telegram_username: str | None,
    ) -> LinkTokenConsumption:
        """Spend a token a Telegram user presented to the shared bot.

        There is no user context: the bot's ingress calls this with the sender
        Telegram reported, and the token itself carries the Member's authority.
        """
        return self.repository.consume_link_token(
            hash_link_token(raw_token),
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            now=datetime.now(UTC),
        )

    def _plugin(self) -> AgentBarnTelegramPlatformPlugin:
        plugin = self.plugins.require(CommunicationPlatform.AGENTBARN_TELEGRAM.value)
        assert isinstance(plugin, AgentBarnTelegramPlatformPlugin)
        return plugin

    def _require_connection(
        self,
        context: CurrentUserContext,
        agent_id: UUID,
        connection_id: UUID,
        permission: PermissionKey,
    ) -> CommunicationConnection:
        scope = self.authorization.authorization_scope(context, permission)
        connection = self.connections.get_active_in_scope(connection_id, agent_id, scope)
        if connection is None:
            self._raise_not_found("Communication Connection")
        if connection.platform_key != CommunicationPlatform.AGENTBARN_TELEGRAM.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only Agent Barn Telegram connections link Telegram accounts",
            )
        return connection

    def _read_token(self, token: AgentBarnTelegramLinkToken) -> TelegramLinkTokenRead:
        username = None
        if token.consumed_at is not None:
            token_status = TelegramLinkTokenStatus.LINKED
            link = self.repository.get_link(token.link_id) if token.link_id is not None else None
            username = link.telegram_username if link is not None else None
        elif token.expires_at <= datetime.now(UTC):
            token_status = TelegramLinkTokenStatus.EXPIRED
        else:
            token_status = TelegramLinkTokenStatus.WAITING
        return TelegramLinkTokenRead(
            id=token.id,
            status=token_status,
            expires_at=token.expires_at,
            telegram_username=username,
        )

    @staticmethod
    def _raise_not_found(what: str) -> NoReturn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")
