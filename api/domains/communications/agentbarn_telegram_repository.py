import enum
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from injector import inject, singleton
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent
from api.domains.agents.repository import agent_scope_predicates
from api.domains.communications.models import (
    AgentBarnTelegramLink,
    AgentBarnTelegramLinkToken,
    CommunicationConnection,
    CommunicationPlatform,
)
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

# Two first-time links for one Telegram user can race on the active-link index;
# the loser retries once and then replaces the winner like any later link.
_CONSUME_ATTEMPTS = 2


class LinkTokenOutcome(str, enum.Enum):
    LINKED = "linked"
    EXPIRED = "expired"
    # Never issued, already used, or its Connection is no longer in use.
    INVALID = "invalid"


@dataclass(frozen=True)
class LinkTokenConsumption:
    outcome: LinkTokenOutcome
    link: AgentBarnTelegramLink | None = None
    # The Telegram user's previous active link, ended by this one.
    replaced_link: AgentBarnTelegramLink | None = None


@inject
@singleton
@dataclass
class AgentBarnTelegramRepository:
    delegate: PostgresRepositoryDelegate

    def create_link_token(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        connection_id: UUID,
        requested_by_membership_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> AgentBarnTelegramLinkToken:
        token = AgentBarnTelegramLinkToken(
            organization_id=organization_id,
            agent_id=agent_id,
            connection_id=connection_id,
            requested_by_membership_id=requested_by_membership_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.delegate.save(token)
        return token

    def get_link_token_in_scope(
        self,
        token_id: UUID,
        connection_id: UUID,
        agent_id: UUID,
        authorization_scope: AuthorizationScope,
    ) -> AgentBarnTelegramLinkToken | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentBarnTelegramLinkToken)
                .join(Agent, col(Agent.id) == col(AgentBarnTelegramLinkToken.agent_id))
                .where(
                    col(AgentBarnTelegramLinkToken.id) == token_id,
                    col(AgentBarnTelegramLinkToken.connection_id) == connection_id,
                    col(AgentBarnTelegramLinkToken.agent_id) == agent_id,
                    *agent_scope_predicates(authorization_scope),
                )
            ).one_or_none()

    def get_link(self, link_id: UUID) -> AgentBarnTelegramLink | None:
        """Unscoped read; callers reach a link only through a token they already read in scope."""
        with Session(self.delegate.engine) as session:
            return session.get(AgentBarnTelegramLink, link_id)

    def consume_link_token(
        self,
        token_hash: str,
        *,
        telegram_user_id: int,
        telegram_username: str | None,
        now: datetime,
    ) -> LinkTokenConsumption:
        """Spend a link token for a Telegram user, replacing their previous link."""
        for attempt in range(_CONSUME_ATTEMPTS):
            try:
                return self._consume(token_hash, telegram_user_id, telegram_username, now)
            except IntegrityError:
                if attempt == _CONSUME_ATTEMPTS - 1:
                    raise
        raise AssertionError("unreachable")

    def _consume(
        self,
        token_hash: str,
        telegram_user_id: int,
        telegram_username: str | None,
        now: datetime,
    ) -> LinkTokenConsumption:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            token = session.exec(
                select(AgentBarnTelegramLinkToken)
                .where(col(AgentBarnTelegramLinkToken.token_hash) == token_hash)
                .with_for_update()
            ).one_or_none()
            if token is None or token.consumed_at is not None:
                return LinkTokenConsumption(LinkTokenOutcome.INVALID)
            if token.expires_at <= now:
                return LinkTokenConsumption(LinkTokenOutcome.EXPIRED)
            connection = session.exec(
                select(CommunicationConnection).where(
                    col(CommunicationConnection.id) == token.connection_id,
                    col(CommunicationConnection.platform_key) == CommunicationPlatform.AGENTBARN_TELEGRAM.value,
                    col(CommunicationConnection.enabled).is_(True),
                    col(CommunicationConnection.retired_at).is_(None),
                )
            ).one_or_none()
            if connection is None:
                return LinkTokenConsumption(LinkTokenOutcome.INVALID)

            previous = session.exec(
                select(AgentBarnTelegramLink)
                .where(
                    col(AgentBarnTelegramLink.telegram_user_id) == telegram_user_id,
                    col(AgentBarnTelegramLink.unlinked_at).is_(None),
                )
                .with_for_update()
            ).one_or_none()
            if previous is not None:
                previous.unlinked_at = now
                session.add(previous)
                # The active-link index must see the old link end before the new one starts.
                session.flush()

            link = AgentBarnTelegramLink(
                organization_id=token.organization_id,
                agent_id=token.agent_id,
                connection_id=token.connection_id,
                linked_by_membership_id=token.requested_by_membership_id,
                telegram_user_id=telegram_user_id,
                telegram_username=telegram_username,
            )
            session.add(link)
            session.flush()
            token.consumed_at = now
            token.link_id = link.id
            session.add(token)
            session.commit()
            return LinkTokenConsumption(LinkTokenOutcome.LINKED, link=link, replaced_link=previous)

    def list_active_links_in_scope(
        self,
        connection_id: UUID,
        agent_id: UUID,
        authorization_scope: AuthorizationScope,
    ) -> list[AgentBarnTelegramLink]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(AgentBarnTelegramLink)
                    .join(Agent, col(Agent.id) == col(AgentBarnTelegramLink.agent_id))
                    .where(
                        col(AgentBarnTelegramLink.connection_id) == connection_id,
                        col(AgentBarnTelegramLink.agent_id) == agent_id,
                        col(AgentBarnTelegramLink.unlinked_at).is_(None),
                        *agent_scope_predicates(authorization_scope),
                    )
                    .order_by(col(AgentBarnTelegramLink.created_at))
                )
            )

    def unlink_in_scope(
        self,
        link_id: UUID,
        connection_id: UUID,
        agent_id: UUID,
        authorization_scope: AuthorizationScope,
        *,
        now: datetime,
    ) -> bool:
        with Session(self.delegate.engine) as session:
            link = session.exec(
                select(AgentBarnTelegramLink)
                .join(Agent, col(Agent.id) == col(AgentBarnTelegramLink.agent_id))
                .where(
                    col(AgentBarnTelegramLink.id) == link_id,
                    col(AgentBarnTelegramLink.connection_id) == connection_id,
                    col(AgentBarnTelegramLink.agent_id) == agent_id,
                    col(AgentBarnTelegramLink.unlinked_at).is_(None),
                    *agent_scope_predicates(authorization_scope),
                )
                .with_for_update(of=AgentBarnTelegramLink)
            ).one_or_none()
            if link is None:
                return False
            link.unlinked_at = now
            session.add(link)
            session.commit()
            return True
