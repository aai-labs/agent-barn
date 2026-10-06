import enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentStatus
from api.domains.agents.repository import agent_scope_predicates
from api.domains.communications.models import (
    AgentBarnTelegramIngressLease,
    AgentBarnTelegramLink,
    AgentBarnTelegramLinkToken,
    AgentBarnTelegramUpdate,
    AgentBarnTelegramUpdateStatus,
    CommunicationConnection,
    CommunicationPlatform,
)
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

# Two first-time links for one Telegram user can race on the active-link index;
# the loser retries once and then replaces the winner like any later link.
_CONSUME_ATTEMPTS = 2
_INGRESS_LEASE_KEY = "shared_bot"


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


@dataclass(frozen=True)
class ForwardTarget:
    """Where a queued update would go, as of now."""

    agent_status: AgentStatus | None
    # False once the Connection is retired, disabled, or its Agent deleted.
    in_use: bool
    driver_key_encrypted: str


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

    def claim_ingress_lease(self, owner: str, *, now: datetime, lease_seconds: int = 60) -> bool:
        """Take or renew the right to poll the shared bot; False while another replica holds it."""
        expires_at = now + timedelta(seconds=lease_seconds)
        statement = (
            pg_insert(AgentBarnTelegramIngressLease)
            .values(key=_INGRESS_LEASE_KEY, owner=owner, expires_at=expires_at)
            .on_conflict_do_update(
                index_elements=["key"],
                set_={"owner": owner, "expires_at": expires_at},
                where=sa.or_(
                    col(AgentBarnTelegramIngressLease.owner) == owner,
                    col(AgentBarnTelegramIngressLease.expires_at) < now,
                ),
            )
            .returning(col(AgentBarnTelegramIngressLease.key))
        )
        with Session(self.delegate.engine) as session:
            claimed = session.exec(statement).first()  # type: ignore[call-overload]
            session.commit()
            return claimed is not None

    def release_ingress_lease(self, owner: str) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.delete(AgentBarnTelegramIngressLease).where(
                    col(AgentBarnTelegramIngressLease.key) == _INGRESS_LEASE_KEY,
                    col(AgentBarnTelegramIngressLease.owner) == owner,
                )
            )  # type: ignore[call-overload]
            session.commit()

    def store_updates(self, updates: list[dict[str, Any]]) -> int:
        """Store received updates once each and return how many were new."""
        rows = [
            AgentBarnTelegramUpdate(update_id=update["update_id"], payload=update).model_dump()
            for update in updates
            if isinstance(update.get("update_id"), int)
        ]
        if not rows:
            return 0
        statement = (
            pg_insert(AgentBarnTelegramUpdate)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_agentbarn_telegram_update_update_id")
            .returning(col(AgentBarnTelegramUpdate.update_id))
        )
        with Session(self.delegate.engine) as session:
            stored = session.exec(statement).all()  # type: ignore[call-overload]
            session.commit()
            return len(stored)

    def received_updates(self, *, limit: int) -> list[AgentBarnTelegramUpdate]:
        """Unprocessed updates in the order Telegram issued them."""
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(AgentBarnTelegramUpdate)
                    .where(col(AgentBarnTelegramUpdate.status) == AgentBarnTelegramUpdateStatus.RECEIVED)
                    .order_by(col(AgentBarnTelegramUpdate.update_id))
                    .limit(limit)
                )
            )

    def settle_update(self, update_id: int) -> None:
        """Mark an update handled by the bot itself and drop its content."""
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(AgentBarnTelegramUpdate)
                .where(col(AgentBarnTelegramUpdate.update_id) == update_id)
                .values(status=AgentBarnTelegramUpdateStatus.HANDLED, payload=None)
            )  # type: ignore[call-overload]
            session.commit()

    def queue_update(self, update_id: int, *, telegram_user_id: int, agent_id: UUID, connection_id: UUID) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(AgentBarnTelegramUpdate)
                .where(col(AgentBarnTelegramUpdate.update_id) == update_id)
                .values(
                    status=AgentBarnTelegramUpdateStatus.QUEUED,
                    telegram_user_id=telegram_user_id,
                    agent_id=agent_id,
                    connection_id=connection_id,
                )
            )  # type: ignore[call-overload]
            session.commit()

    def find_routable_link(self, telegram_user_id: int) -> AgentBarnTelegramLink | None:
        """The user's active link, while its Connection is in use and its Agent exists."""
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentBarnTelegramLink)
                .join(
                    CommunicationConnection, col(CommunicationConnection.id) == col(AgentBarnTelegramLink.connection_id)
                )
                .join(Agent, col(Agent.id) == col(AgentBarnTelegramLink.agent_id))
                .where(
                    col(AgentBarnTelegramLink.telegram_user_id) == telegram_user_id,
                    col(AgentBarnTelegramLink.unlinked_at).is_(None),
                    col(CommunicationConnection.platform_key) == CommunicationPlatform.AGENTBARN_TELEGRAM.value,
                    col(CommunicationConnection.enabled).is_(True),
                    col(CommunicationConnection.retired_at).is_(None),
                    col(Agent.deleted_at).is_(None),
                )
            ).one_or_none()

    def end_active_link(self, telegram_user_id: int, *, now: datetime) -> bool:
        with Session(self.delegate.engine) as session:
            ended = session.exec(
                sa.update(AgentBarnTelegramLink)
                .where(
                    col(AgentBarnTelegramLink.telegram_user_id) == telegram_user_id,
                    col(AgentBarnTelegramLink.unlinked_at).is_(None),
                )
                .values(unlinked_at=now)
                .returning(col(AgentBarnTelegramLink.id))
            ).first()  # type: ignore[call-overload]
            session.commit()
            return ended is not None

    def agent_names(self, agent_ids: list[UUID]) -> dict[UUID, str]:
        with Session(self.delegate.engine) as session:
            rows = session.exec(select(Agent.id, Agent.name).where(col(Agent.id).in_(agent_ids))).all()
            return {agent_id: name for agent_id, name in rows}

    def queue_heads(self, *, limit: int) -> list[AgentBarnTelegramUpdate]:
        """Each Telegram user's oldest queued update; later ones wait behind it."""
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(AgentBarnTelegramUpdate)
                    .where(col(AgentBarnTelegramUpdate.status) == AgentBarnTelegramUpdateStatus.QUEUED)
                    .distinct(col(AgentBarnTelegramUpdate.telegram_user_id))
                    .order_by(col(AgentBarnTelegramUpdate.telegram_user_id), col(AgentBarnTelegramUpdate.update_id))
                    .limit(limit)
                )
            )

    def queue_head_for_user(self, telegram_user_id: int) -> AgentBarnTelegramUpdate | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentBarnTelegramUpdate)
                .where(
                    col(AgentBarnTelegramUpdate.status) == AgentBarnTelegramUpdateStatus.QUEUED,
                    col(AgentBarnTelegramUpdate.telegram_user_id) == telegram_user_id,
                )
                .order_by(col(AgentBarnTelegramUpdate.update_id))
                .limit(1)
            ).first()

    def forward_target(self, agent_id: UUID, connection_id: UUID) -> ForwardTarget | None:
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(Agent.status, Agent.deleted_at, CommunicationConnection)
                .join(CommunicationConnection, col(CommunicationConnection.agent_id) == col(Agent.id))
                .where(col(Agent.id) == agent_id, col(CommunicationConnection.id) == connection_id)
            ).first()
            if row is None:
                return None
            status, deleted_at, connection = row
            return ForwardTarget(
                agent_status=status,
                in_use=deleted_at is None and connection.enabled and connection.retired_at is None,
                driver_key_encrypted=connection.driver_key_encrypted,
            )

    def mark_forwarded(self, update_id: int) -> None:
        self._finish(update_id, AgentBarnTelegramUpdateStatus.FORWARDED)

    def drop(self, update_id: int) -> None:
        self._finish(update_id, AgentBarnTelegramUpdateStatus.DROPPED)

    def _finish(self, update_id: int, status: AgentBarnTelegramUpdateStatus) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(AgentBarnTelegramUpdate)
                .where(col(AgentBarnTelegramUpdate.update_id) == update_id)
                .values(status=status, payload=None)
            )  # type: ignore[call-overload]
            session.commit()

    def schedule_retry(self, update_id: int, *, at: datetime) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(AgentBarnTelegramUpdate)
                .where(col(AgentBarnTelegramUpdate.update_id) == update_id)
                .values(
                    attempt_count=AgentBarnTelegramUpdate.attempt_count + 1,  # type: ignore[operator]
                    next_attempt_at=at,
                )
            )  # type: ignore[call-overload]
            session.commit()

    def claim_notice(self, telegram_user_id: int, *, now: datetime) -> bool:
        """Record that the user was told their Agent is unavailable; False if already told."""
        with Session(self.delegate.engine) as session:
            already = session.exec(
                select(AgentBarnTelegramUpdate.id).where(
                    col(AgentBarnTelegramUpdate.status) == AgentBarnTelegramUpdateStatus.QUEUED,
                    col(AgentBarnTelegramUpdate.telegram_user_id) == telegram_user_id,
                    col(AgentBarnTelegramUpdate.notice_sent_at).is_not(None),
                )
            ).first()
            if already is not None:
                return False
            session.exec(
                sa.update(AgentBarnTelegramUpdate)
                .where(
                    col(AgentBarnTelegramUpdate.status) == AgentBarnTelegramUpdateStatus.QUEUED,
                    col(AgentBarnTelegramUpdate.telegram_user_id) == telegram_user_id,
                )
                .values(notice_sent_at=now)
            )  # type: ignore[call-overload]
            session.commit()
            return True

    def drop_expired(self, *, received_before: datetime) -> dict[int, int]:
        """Drop queued updates received before the cutoff; return how many each Telegram user lost."""
        with Session(self.delegate.engine) as session:
            dropped = session.exec(
                sa.update(AgentBarnTelegramUpdate)
                .where(
                    col(AgentBarnTelegramUpdate.status) == AgentBarnTelegramUpdateStatus.QUEUED,
                    col(AgentBarnTelegramUpdate.created_at) < received_before,
                )
                .values(status=AgentBarnTelegramUpdateStatus.DROPPED, payload=None)
                .returning(col(AgentBarnTelegramUpdate.telegram_user_id))
            ).all()  # type: ignore[call-overload]
            session.commit()
            counts: dict[int, int] = {}
            for (user_id,) in dropped:
                if user_id is not None:
                    counts[user_id] = counts.get(user_id, 0) + 1
            return counts

    def proxy_connection(self, connection_id: UUID) -> CommunicationConnection | None:
        """An Agent Barn Telegram Connection that may still use the proxy."""
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(CommunicationConnection)
                .join(Agent, col(Agent.id) == col(CommunicationConnection.agent_id))
                .where(
                    col(CommunicationConnection.id) == connection_id,
                    col(CommunicationConnection.platform_key) == CommunicationPlatform.AGENTBARN_TELEGRAM.value,
                    col(CommunicationConnection.enabled).is_(True),
                    col(CommunicationConnection.retired_at).is_(None),
                    col(Agent.deleted_at).is_(None),
                )
            ).one_or_none()

    def linked_user_ids(self, connection_id: UUID) -> set[int]:
        with Session(self.delegate.engine) as session:
            return set(
                session.exec(
                    select(AgentBarnTelegramLink.telegram_user_id).where(
                        col(AgentBarnTelegramLink.connection_id) == connection_id,
                        col(AgentBarnTelegramLink.unlinked_at).is_(None),
                    )
                )
            )

    def end_link_for_connection(self, connection_id: UUID, telegram_user_id: int, *, now: datetime) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(AgentBarnTelegramLink)
                .where(
                    col(AgentBarnTelegramLink.connection_id) == connection_id,
                    col(AgentBarnTelegramLink.telegram_user_id) == telegram_user_id,
                    col(AgentBarnTelegramLink.unlinked_at).is_(None),
                )
                .values(unlinked_at=now)
            )  # type: ignore[call-overload]
            session.commit()
