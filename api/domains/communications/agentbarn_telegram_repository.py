import enum
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentStatus
from api.domains.agents.repository import agent_scope_predicates
from api.domains.communications.agentbarn_telegram_messages import sender_id
from api.domains.communications.models import (
    AgentBarnTelegramConnectionSecret,
    AgentBarnTelegramFile,
    AgentBarnTelegramIngressLease,
    AgentBarnTelegramLink,
    AgentBarnTelegramLinkToken,
    AgentBarnTelegramMessage,
    AgentBarnTelegramUpdate,
    AgentBarnTelegramUpdateStatus,
    CommunicationConnection,
    CommunicationPlatform,
)
from api.domains.events.catalog import (
    EVENT_REGISTRY,
    TELEGRAM_ACCOUNT_LINKED,
    TELEGRAM_ACCOUNT_UNLINKED,
    TELEGRAM_FIRST_MESSAGE_RECEIVED,
)
from api.domains.events.models import ActorIdentity, ActorIdentityType, SubjectIdentity, SubjectIdentityType
from api.domains.events.repository import OutboxMessageRepository
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

# Two first-time links for one Telegram user can race on the active-link index;
# the loser retries once and then replaces the winner like any later link.
_CONSUME_ATTEMPTS = 2
_INGRESS_LEASE_KEY = "shared_bot"
RELINKED = "relinked"
USER_REMOVED = "user_removed"
BLOCKED_BOT = "blocked_bot"
ACCESS_LOST = "access_lost"


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
    delivery_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class ForwardTarget:
    """Where a queued update would go, as of now."""

    agent_status: AgentStatus | None
    # False once the Connection is retired, disabled, or its Agent deleted.
    in_use: bool
    # The sender's active link to this Connection; None once they were unlinked or switched.
    link: AgentBarnTelegramLink | None


@inject
@singleton
@dataclass
class AgentBarnTelegramRepository:
    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

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
            delivery_ids = self._stage_link_event(session, TELEGRAM_ACCOUNT_LINKED, link, now)
            if previous is not None:
                delivery_ids += self._stage_link_event(session, TELEGRAM_ACCOUNT_UNLINKED, previous, now, RELINKED)
            session.commit()
            return LinkTokenConsumption(
                LinkTokenOutcome.LINKED, link=link, replaced_link=previous, delivery_ids=tuple(delivery_ids)
            )

    def _stage_link_event(
        self,
        session: Session,
        event_name: str,
        link: AgentBarnTelegramLink,
        now: datetime,
        reason: str | None = None,
        actor: ActorIdentity | None = None,
    ) -> list[UUID]:
        payload: dict[str, Any] = {
            "organization_id": link.organization_id,
            "agent_id": link.agent_id,
            "connection_id": link.connection_id,
            "link_id": link.id,
        }
        if reason is not None:
            payload["reason"] = reason
        event = EVENT_REGISTRY.build_event(
            event_name=event_name,
            schema_version=1,
            occurred_at=now,
            organization_id=link.organization_id,
            actor=actor
            or ActorIdentity(
                type=ActorIdentityType.MEMBERSHIP, id=link.linked_by_membership_id, organization_id=link.organization_id
            ),
            subject=SubjectIdentity(
                type=SubjectIdentityType.AGENT, id=link.agent_id, organization_id=link.organization_id
            ),
            correlation_id=uuid4(),
            payload=payload,
        )
        self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
        return self.outbox_repository.delivery_ids_for_event(session, event.event_id)

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
        actor: ActorIdentity,
    ) -> tuple[UUID, ...] | None:
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
                return None
            link.unlinked_at = now
            session.add(link)
            delivery_ids = self._stage_link_event(session, TELEGRAM_ACCOUNT_UNLINKED, link, now, USER_REMOVED, actor)
            session.commit()
            return tuple(delivery_ids)

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
            AgentBarnTelegramUpdate(
                update_id=update["update_id"], payload=update, telegram_user_id=sender_id(update)
            ).model_dump()
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

    def received_updates(self, *, now: datetime, limit: int) -> list[AgentBarnTelegramUpdate]:
        """Unprocessed updates in the order Telegram issued them, leaving out senders who must wait.

        A sender waits while one of their updates is backing off after a failure;
        all of theirs are left out, so their order is kept and nobody else waits.
        """
        waiting = select(AgentBarnTelegramUpdate.telegram_user_id).where(
            col(AgentBarnTelegramUpdate.status) == AgentBarnTelegramUpdateStatus.RECEIVED,
            col(AgentBarnTelegramUpdate.telegram_user_id).is_not(None),
            col(AgentBarnTelegramUpdate.next_attempt_at) > now,
        )
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(AgentBarnTelegramUpdate)
                    .where(
                        col(AgentBarnTelegramUpdate.status) == AgentBarnTelegramUpdateStatus.RECEIVED,
                        sa.or_(
                            col(AgentBarnTelegramUpdate.next_attempt_at).is_(None),
                            col(AgentBarnTelegramUpdate.next_attempt_at) <= now,
                        ),
                        sa.or_(
                            col(AgentBarnTelegramUpdate.telegram_user_id).is_(None),
                            col(AgentBarnTelegramUpdate.telegram_user_id).not_in(waiting),
                        ),
                    )
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

    def record_processing_failure(self, update_id: int, *, retry_at: datetime) -> int:
        """Count a failed processing pass, hold the update until `retry_at`, and return its attempts."""
        with Session(self.delegate.engine) as session:
            attempts = session.exec(
                sa.update(AgentBarnTelegramUpdate)
                .where(col(AgentBarnTelegramUpdate.update_id) == update_id)
                .values(
                    attempt_count=AgentBarnTelegramUpdate.attempt_count + 1,  # type: ignore[operator]
                    next_attempt_at=retry_at,
                )
                .returning(col(AgentBarnTelegramUpdate.attempt_count))
            ).first()  # type: ignore[call-overload]
            session.commit()
            return attempts[0] if attempts else 0

    def queue_update(
        self,
        update_id: int,
        *,
        telegram_user_id: int,
        agent_id: UUID,
        connection_id: UUID,
        payload: dict[str, Any],
        messages: Iterable[tuple[int, int]] = (),
        files: Iterable[str] = (),
        first_message_link_id: UUID | None = None,
    ) -> tuple[UUID, ...]:
        """Queue an update, as the Agent may see it, and make its messages and files the Connection's."""
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(AgentBarnTelegramUpdate)
                .where(col(AgentBarnTelegramUpdate.update_id) == update_id)
                .values(
                    status=AgentBarnTelegramUpdateStatus.QUEUED,
                    telegram_user_id=telegram_user_id,
                    agent_id=agent_id,
                    connection_id=connection_id,
                    payload=payload,
                    # Forwarding counts its own attempts, and sets its own retries, from here.
                    attempt_count=0,
                    next_attempt_at=None,
                )
            )  # type: ignore[call-overload]
            self._insert_ownership(session, connection_id, messages, files)
            delivery_ids = (
                self._stage_first_message(session, first_message_link_id) if first_message_link_id is not None else []
            )
            session.commit()
            return tuple(delivery_ids)

    def _stage_first_message(self, session: Session, link_id: UUID) -> list[UUID]:
        now = datetime.now(UTC)
        link = session.scalars(
            sa.update(AgentBarnTelegramLink)
            .where(
                col(AgentBarnTelegramLink.id) == link_id,
                col(AgentBarnTelegramLink.unlinked_at).is_(None),
                col(AgentBarnTelegramLink.first_message_at).is_(None),
            )
            .values(first_message_at=now)
            .returning(AgentBarnTelegramLink)
        ).first()
        return self._stage_link_event(session, TELEGRAM_FIRST_MESSAGE_RECEIVED, link, now) if link is not None else []

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

    def end_active_link(self, telegram_user_id: int, *, now: datetime, reason: str) -> tuple[UUID, ...]:
        return self._end_link(
            [
                col(AgentBarnTelegramLink.telegram_user_id) == telegram_user_id,
                col(AgentBarnTelegramLink.unlinked_at).is_(None),
            ],
            now=now,
            reason=reason,
        )

    def _end_link(self, conditions: list[Any], *, now: datetime, reason: str) -> tuple[UUID, ...]:
        with Session(self.delegate.engine) as session:
            link = session.scalars(
                sa.update(AgentBarnTelegramLink)
                .where(*conditions)
                .values(unlinked_at=now)
                .returning(AgentBarnTelegramLink)
            ).first()
            delivery_ids = (
                self._stage_link_event(session, TELEGRAM_ACCOUNT_UNLINKED, link, now, reason)
                if link is not None
                else []
            )
            session.commit()
            return tuple(delivery_ids)

    def agent_names(self, agent_ids: list[UUID]) -> dict[UUID, str]:
        with Session(self.delegate.engine) as session:
            rows = session.exec(select(Agent.id, Agent.name).where(col(Agent.id).in_(agent_ids))).all()
            return {agent_id: name for agent_id, name in rows}

    def queue_heads(self, *, now: datetime, limit: int) -> list[AgentBarnTelegramUpdate]:
        """Each Telegram user's oldest queued update that is due now, longest-waiting first.

        Later updates wait behind their user's head. Filtering for due heads before
        the limit keeps users whose head is waiting on a retry from crowding out
        users who are ready.
        """
        heads = (
            select(AgentBarnTelegramUpdate.id)
            .where(col(AgentBarnTelegramUpdate.status) == AgentBarnTelegramUpdateStatus.QUEUED)
            .distinct(col(AgentBarnTelegramUpdate.telegram_user_id))
            .order_by(col(AgentBarnTelegramUpdate.telegram_user_id), col(AgentBarnTelegramUpdate.update_id))
        )
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(AgentBarnTelegramUpdate)
                    .where(
                        col(AgentBarnTelegramUpdate.id).in_(heads),
                        sa.or_(
                            col(AgentBarnTelegramUpdate.next_attempt_at).is_(None),
                            col(AgentBarnTelegramUpdate.next_attempt_at) <= now,
                        ),
                    )
                    .order_by(
                        sa.func.coalesce(
                            col(AgentBarnTelegramUpdate.next_attempt_at), col(AgentBarnTelegramUpdate.created_at)
                        )
                    )
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

    def forward_target(self, agent_id: UUID, connection_id: UUID, telegram_user_id: int) -> ForwardTarget | None:
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(Agent.status, Agent.deleted_at, CommunicationConnection)
                .join(CommunicationConnection, col(CommunicationConnection.agent_id) == col(Agent.id))
                .where(col(Agent.id) == agent_id, col(CommunicationConnection.id) == connection_id)
            ).first()
            if row is None:
                return None
            status, deleted_at, connection = row
            link = session.exec(
                select(AgentBarnTelegramLink).where(
                    col(AgentBarnTelegramLink.connection_id) == connection_id,
                    col(AgentBarnTelegramLink.telegram_user_id) == telegram_user_id,
                    col(AgentBarnTelegramLink.unlinked_at).is_(None),
                )
            ).one_or_none()
            return ForwardTarget(
                agent_status=status,
                in_use=deleted_at is None and connection.enabled and connection.retired_at is None,
                link=link,
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

    def record_rejection(self, update_id: int, *, retry_at: datetime) -> int:
        """Count one refusal by the Agent's webhook and schedule a retry; the refusals so far."""
        with Session(self.delegate.engine) as session:
            rejected = session.exec(
                sa.update(AgentBarnTelegramUpdate)
                .where(col(AgentBarnTelegramUpdate.update_id) == update_id)
                .values(
                    attempt_count=AgentBarnTelegramUpdate.attempt_count + 1,  # type: ignore[operator]
                    rejected_count=AgentBarnTelegramUpdate.rejected_count + 1,  # type: ignore[operator]
                    next_attempt_at=retry_at,
                )
                .returning(col(AgentBarnTelegramUpdate.rejected_count))
            ).first()  # type: ignore[call-overload]
            session.commit()
            return rejected[0] if rejected else 0

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

    def connection_secret_encrypted(self, connection_id: UUID) -> str | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentBarnTelegramConnectionSecret.secret_encrypted).where(
                    col(AgentBarnTelegramConnectionSecret.connection_id) == connection_id
                )
            ).first()

    def create_connection_secret(self, connection_id: UUID, secret_encrypted: str) -> str:
        """Store a Connection's secret unless it has one; return the one it keeps."""
        with Session(self.delegate.engine) as session:
            session.exec(
                pg_insert(AgentBarnTelegramConnectionSecret)
                .values(
                    AgentBarnTelegramConnectionSecret(
                        connection_id=connection_id, secret_encrypted=secret_encrypted
                    ).model_dump()
                )
                .on_conflict_do_nothing(index_elements=["connection_id"])
            )  # type: ignore[call-overload]
            session.commit()
        stored = self.connection_secret_encrypted(connection_id)
        assert stored is not None
        return stored

    def purge_settled(self, *, settled_before: datetime) -> int:
        """Delete updates settled before the cutoff; return how many went.

        A settled row only guards against Telegram re-delivering its update,
        which Telegram stops doing within a day, so old ones serve no purpose.
        """
        with Session(self.delegate.engine) as session:
            purged = session.exec(
                sa.delete(AgentBarnTelegramUpdate)
                .where(
                    col(AgentBarnTelegramUpdate.status).in_(
                        [
                            AgentBarnTelegramUpdateStatus.HANDLED,
                            AgentBarnTelegramUpdateStatus.FORWARDED,
                            AgentBarnTelegramUpdateStatus.DROPPED,
                        ]
                    ),
                    col(AgentBarnTelegramUpdate.updated_at) < settled_before,
                )
                .returning(col(AgentBarnTelegramUpdate.update_id))
            ).all()  # type: ignore[call-overload]
            session.commit()
            return len(purged)

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

    def active_links(self, connection_id: UUID, telegram_user_ids: Iterable[int]) -> list[AgentBarnTelegramLink]:
        """The Connection's active links among these Telegram users."""
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(AgentBarnTelegramLink).where(
                        col(AgentBarnTelegramLink.connection_id) == connection_id,
                        col(AgentBarnTelegramLink.telegram_user_id).in_(set(telegram_user_ids)),
                        col(AgentBarnTelegramLink.unlinked_at).is_(None),
                    )
                )
            )

    def end_link_for_connection(
        self, connection_id: UUID, telegram_user_id: int, *, now: datetime, reason: str
    ) -> tuple[UUID, ...]:
        return self._end_link(
            [
                col(AgentBarnTelegramLink.connection_id) == connection_id,
                col(AgentBarnTelegramLink.telegram_user_id) == telegram_user_id,
                col(AgentBarnTelegramLink.unlinked_at).is_(None),
            ],
            now=now,
            reason=reason,
        )

    def record_ownership(
        self,
        connection_id: UUID,
        *,
        messages: Iterable[tuple[int, int]] = (),
        files: Iterable[str] = (),
    ) -> None:
        """Record (chat, message) pairs and file ids as the Connection's. A message keeps its first owner."""
        with Session(self.delegate.engine) as session:
            self._insert_ownership(session, connection_id, messages, files)
            session.commit()

    @staticmethod
    def _insert_ownership(
        session: Session,
        connection_id: UUID,
        messages: Iterable[tuple[int, int]],
        files: Iterable[str],
    ) -> None:
        message_rows = [
            AgentBarnTelegramMessage(chat_id=chat_id, message_id=message_id, connection_id=connection_id).model_dump()
            for chat_id, message_id in set(messages)
        ]
        file_rows = [
            AgentBarnTelegramFile(connection_id=connection_id, file_id=file_id).model_dump() for file_id in set(files)
        ]
        if message_rows:
            session.exec(
                pg_insert(AgentBarnTelegramMessage)
                .values(message_rows)
                .on_conflict_do_nothing(constraint="uq_agentbarn_telegram_message_chat_message")
            )  # type: ignore[call-overload]
        if file_rows:
            session.exec(
                pg_insert(AgentBarnTelegramFile)
                .values(file_rows)
                .on_conflict_do_nothing(constraint="uq_agentbarn_telegram_file_connection_file")
            )  # type: ignore[call-overload]

    def owns_messages(self, connection_id: UUID, messages: Iterable[tuple[int, int]]) -> bool:
        wanted = set(messages)
        if not wanted:
            return True
        with Session(self.delegate.engine) as session:
            owned = session.exec(
                select(sa.func.count()).where(
                    col(AgentBarnTelegramMessage.connection_id) == connection_id,
                    sa.tuple_(col(AgentBarnTelegramMessage.chat_id), col(AgentBarnTelegramMessage.message_id)).in_(
                        list(wanted)
                    ),
                )
            ).one()
        return owned == len(wanted)

    def owns_files(self, connection_id: UUID, file_ids: Iterable[str]) -> bool:
        wanted = set(file_ids)
        if not wanted:
            return True
        with Session(self.delegate.engine) as session:
            owned = session.exec(
                select(sa.func.count()).where(
                    col(AgentBarnTelegramFile.connection_id) == connection_id,
                    col(AgentBarnTelegramFile.file_id).in_(wanted),
                )
            ).one()
        return owned == len(wanted)
