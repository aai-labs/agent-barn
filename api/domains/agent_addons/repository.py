from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import Session, col, select

from api.domains.agent_addons.models import (
    ACTIVE_ADDON_STATES,
    MAX_ACTIVE_ADDONS_PER_AGENT,
    AgentAddon,
    AgentAddonEmailReceipt,
    AgentAddonKind,
    AgentAddonRow,
    AgentAddonState,
    ApprovedAddon,
    PlatformAgentAddonRow,
)
from api.domains.agents.models import Agent
from api.domains.events import ActorIdentity, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import (
    AGENT_ADDON_APPROVED,
    AGENT_ADDON_REJECTED,
    AGENT_ADDON_REQUESTED,
    AGENT_ADDON_REVOKED,
    AGENT_ADDON_WITHDRAWN,
    EVENT_REGISTRY,
)
from api.domains.events.repository import OutboxMessageRepository
from api.domains.organizations.models import Organization
from api.domains.users.models import User
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import Pagination

EVENT_BY_STATE = {
    AgentAddonState.PENDING: AGENT_ADDON_REQUESTED,
    AgentAddonState.APPROVED: AGENT_ADDON_APPROVED,
    AgentAddonState.REJECTED: AGENT_ADDON_REJECTED,
    AgentAddonState.WITHDRAWN: AGENT_ADDON_WITHDRAWN,
    AgentAddonState.REVOKED: AGENT_ADDON_REVOKED,
}


class AgentAddonLimitReached(Exception):
    """The Agent already has as many Pending and Approved add-ons as it may."""


class AgentAddonNameTaken(Exception):
    """The Agent already has an active add-on of this kind and name."""


class AgentAddonStateConflict(Exception):
    """The add-on is in a state this change cannot start from."""

    def __init__(self, state: AgentAddonState) -> None:
        super().__init__(state.value)
        self.state = state


@dataclass(frozen=True)
class AgentAddonChange:
    addon: AgentAddon
    delivery_ids: list[UUID]


def _stage_state_change(
    session: Session,
    outbox_repository: OutboxMessageRepository,
    addon: AgentAddon,
    agent_name: str,
    *,
    previous_state: AgentAddonState | None,
    actor: ActorIdentity,
    actor_display: str,
    correlation_id: UUID,
) -> UUID:
    event = EVENT_REGISTRY.build_event(
        event_name=EVENT_BY_STATE[addon.state],
        schema_version=1,
        occurred_at=datetime.now(UTC),
        organization_id=addon.organization_id,
        actor=actor,
        subject=SubjectIdentity(
            type=SubjectIdentityType.AGENT,
            id=addon.agent_id,
            organization_id=addon.organization_id,
        ),
        correlation_id=correlation_id,
        payload={
            "organization_id": addon.organization_id,
            "agent_id": addon.agent_id,
            "addon_id": addon.id,
            "kind": AgentAddonKind(addon.kind).value,
            "name": addon.name,
            **addon.spec,
            "request_reason": addon.reason,
            "state": AgentAddonState(addon.state).value,
            "previous_state": AgentAddonState(previous_state).value if previous_state is not None else None,
            "reason": addon.rejection_reason,
            "actor_display": actor_display,
            "subject_display": agent_name,
        },
    )
    outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
    return event.event_id


def stage_pending_addons_withdrawn(
    session: Session,
    outbox_repository: OutboxMessageRepository,
    agent: Agent,
    *,
    actor: ActorIdentity,
    actor_display: str,
    correlation_id: UUID,
) -> list[UUID]:
    """Withdraw a deleted Agent's Pending add-ons in the deletion's transaction.

    Approved ones stay Approved as history: the Agent will never start again, and its add-ons
    volume goes with its other resources. Returns the staged Event ids.
    """
    pending = session.exec(
        select(AgentAddon)
        .where(
            col(AgentAddon.agent_id) == agent.id,
            col(AgentAddon.organization_id) == agent.organization_id,
            col(AgentAddon.state) == AgentAddonState.PENDING,
        )
        .order_by(col(AgentAddon.created_at), col(AgentAddon.id))
        .with_for_update()
    ).all()
    event_ids = []
    now = datetime.now(UTC)
    for addon in pending:
        addon.state = AgentAddonState.WITHDRAWN
        addon.decided_at = now
        addon.updated_at = now
        session.add(addon)
        session.flush()
        event_ids.append(
            _stage_state_change(
                session,
                outbox_repository,
                addon,
                agent.name,
                previous_state=AgentAddonState.PENDING,
                actor=actor,
                actor_display=actor_display,
                correlation_id=correlation_id,
            )
        )
    return event_ids


@inject
@singleton
@dataclass
class AgentAddonRepository:
    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    def list_for_agent(self, agent_id: UUID, organization_id: UUID) -> list[AgentAddonRow]:
        """One Agent's add-ons, newest first, each with who asked for it.

        The caller has already authorized the Agent; the Organization is part of the filter
        so an id from another Organization can never match.
        """
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(AgentAddon, User.full_name, User.email)
                .outerjoin(User, col(User.id) == col(AgentAddon.requested_by_user_id))
                .where(col(AgentAddon.agent_id) == agent_id, col(AgentAddon.organization_id) == organization_id)
                .order_by(col(AgentAddon.created_at).desc(), col(AgentAddon.id).desc())
            ).all()
        return [AgentAddonRow(addon, name, email) for addon, name, email in rows]

    def get_for_agent(self, addon_id: UUID, agent_id: UUID, organization_id: UUID) -> AgentAddonRow | None:
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(AgentAddon, User.full_name, User.email)
                .outerjoin(User, col(User.id) == col(AgentAddon.requested_by_user_id))
                .where(
                    col(AgentAddon.id) == addon_id,
                    col(AgentAddon.agent_id) == agent_id,
                    col(AgentAddon.organization_id) == organization_id,
                )
            ).first()
        return AgentAddonRow(*row) if row is not None else None

    def create_with_event(
        self,
        addon: AgentAddon,
        *,
        actor: ActorIdentity,
        actor_display: str,
    ) -> AgentAddonChange | None:
        """Record a Pending request and stage `agent.addon.requested`.

        Holds the Agent's row lock while it counts, so two requests at once cannot both take
        the last place. None when the Agent was deleted meanwhile. Raises
        AgentAddonLimitReached and AgentAddonNameTaken.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            agent = session.exec(
                select(Agent)
                .where(
                    col(Agent.id) == addon.agent_id,
                    col(Agent.organization_id) == addon.organization_id,
                    col(Agent.deleted_at).is_(None),
                )
                .with_for_update()
            ).first()
            if agent is None:
                return None
            active = session.exec(
                select(func.count())
                .select_from(AgentAddon)
                .where(
                    col(AgentAddon.agent_id) == agent.id,
                    col(AgentAddon.state).in_([state.value for state in ACTIVE_ADDON_STATES]),
                )
            ).one()
            if active >= MAX_ACTIVE_ADDONS_PER_AGENT:
                raise AgentAddonLimitReached
            addon.state = AgentAddonState.PENDING
            session.add(addon)
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                if "uq_agent_addons_active_name" in str(exc.orig):
                    raise AgentAddonNameTaken from None
                raise
            event_id = _stage_state_change(
                session,
                self.outbox_repository,
                addon,
                agent.name,
                previous_state=None,
                actor=actor,
                actor_display=actor_display,
                correlation_id=uuid4(),
            )
            delivery_ids = self._delivery_ids(session, [event_id])
            session.commit()
            return AgentAddonChange(addon=addon, delivery_ids=delivery_ids)

    def change_state_with_event(
        self,
        addon_id: UUID,
        *,
        to_state: AgentAddonState,
        from_states: Collection[AgentAddonState],
        actor: ActorIdentity,
        actor_display: str,
        decided_by_user_id: UUID | None,
        rejection_reason: str | None = None,
        organization_id: UUID | None = None,
        agent_id: UUID | None = None,
    ) -> AgentAddonChange | None:
        """Move one add-on to `to_state` from one of `from_states`, and stage its Event.

        Under the add-on's row lock, so two decisions cannot both apply. Already in
        `to_state` is a no-op that stages nothing and keeps the first decision (its reason
        included). Any other state raises AgentAddonStateConflict. `organization_id` and
        `agent_id` narrow the lookup for the Organization's own routes. None when absent.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            query = select(AgentAddon).where(col(AgentAddon.id) == addon_id)
            if organization_id is not None:
                query = query.where(col(AgentAddon.organization_id) == organization_id)
            if agent_id is not None:
                query = query.where(col(AgentAddon.agent_id) == agent_id)
            addon = session.exec(query.with_for_update()).first()
            if addon is None:
                return None
            if addon.state == to_state:
                return AgentAddonChange(addon=addon, delivery_ids=[])
            if addon.state not in from_states:
                raise AgentAddonStateConflict(AgentAddonState(addon.state))
            agent_name = session.exec(select(Agent.name).where(col(Agent.id) == addon.agent_id)).one()
            previous_state = addon.state
            now = datetime.now(UTC)
            addon.state = to_state
            addon.decided_by_user_id = decided_by_user_id
            addon.decided_at = now
            addon.updated_at = now
            addon.rejection_reason = rejection_reason if to_state == AgentAddonState.REJECTED else None
            session.add(addon)
            session.flush()
            event_id = _stage_state_change(
                session,
                self.outbox_repository,
                addon,
                agent_name,
                previous_state=previous_state,
                actor=actor,
                actor_display=actor_display,
                correlation_id=uuid4(),
            )
            delivery_ids = self._delivery_ids(session, [event_id])
            session.commit()
            return AgentAddonChange(addon=addon, delivery_ids=delivery_ids)

    def approved_for_agent(self, agent_id: UUID) -> list[ApprovedAddon]:
        """What provisioning installs, in the order it installs it: by approval, oldest first."""
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(AgentAddon)
                .where(col(AgentAddon.agent_id) == agent_id, col(AgentAddon.state) == AgentAddonState.APPROVED)
                .order_by(col(AgentAddon.decided_at), col(AgentAddon.id))
            ).all()
        return [ApprovedAddon(a.id, AgentAddonKind(a.kind), a.name, dict(a.spec), a.reason) for a in rows]

    def ever_approved(self, agent_id: UUID) -> bool:
        """An add-on that is or was approved: Approved now, or Revoked since."""
        with Session(self.delegate.engine) as session:
            found = session.exec(
                select(AgentAddon.id)
                .where(
                    col(AgentAddon.agent_id) == agent_id,
                    col(AgentAddon.state).in_([AgentAddonState.APPROVED, AgentAddonState.REVOKED]),
                )
                .limit(1)
            ).first()
        return found is not None

    def approved_for_agents(self, agent_ids: list[UUID]) -> Mapping[UUID, list[ApprovedAddon]]:
        """`approved_for_agent` for a page of Agents in one query; Agents with none are absent."""
        if not agent_ids:
            return {}
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(AgentAddon)
                .where(
                    col(AgentAddon.agent_id).in_(agent_ids),
                    col(AgentAddon.state) == AgentAddonState.APPROVED,
                )
                .order_by(col(AgentAddon.agent_id), col(AgentAddon.decided_at), col(AgentAddon.id))
            ).all()
        by_agent: dict[UUID, list[ApprovedAddon]] = {}
        for a in rows:
            by_agent.setdefault(a.agent_id, []).append(
                ApprovedAddon(a.id, AgentAddonKind(a.kind), a.name, dict(a.spec), a.reason)
            )
        return by_agent

    def find_platform_requests(
        self,
        *,
        state: AgentAddonState | None,
        organization_id: UUID | None,
        search: str | None,
        pagination: Pagination,
    ) -> tuple[list[PlatformAgentAddonRow], int]:
        """A page of add-on requests across every Organization, newest first, and the total.

        Platform-wide by design, for the Platform Add-ons page behind `require_platform_admin`.
        `search` matches the add-on's, the Agent's or the Organization's name.
        """
        query = self._platform_rows()
        if state is not None:
            query = query.where(col(AgentAddon.state) == state)
        if organization_id is not None:
            query = query.where(col(AgentAddon.organization_id) == organization_id)
        if search:
            pattern = f"%{search}%"
            query = query.where(
                or_(
                    col(AgentAddon.name).ilike(pattern),
                    col(Agent.name).ilike(pattern),
                    col(Organization.name).ilike(pattern),
                )
            )
        total_query = sa.select(func.count()).select_from(query.order_by(None).subquery())
        page_query = (
            query.order_by(col(AgentAddon.created_at).desc(), col(AgentAddon.id).desc())
            .offset((pagination.page - 1) * pagination.size)
            .limit(pagination.size)
        )
        with self.delegate.engine.connect() as connection:
            total = connection.execute(total_query).scalar_one()
            rows = [PlatformAgentAddonRow(*row) for row in connection.execute(page_query).all()]
        return rows, total

    def get_platform_request(self, addon_id: UUID) -> PlatformAgentAddonRow | None:
        query = self._platform_rows().where(col(AgentAddon.id) == addon_id)
        with self.delegate.engine.connect() as connection:
            row = connection.execute(query).first()
        return PlatformAgentAddonRow(*row) if row is not None else None

    @staticmethod
    def _platform_rows():
        # The column list is the allowlist: see PlatformAgentAddonRow.
        requester = aliased(User)
        decider = aliased(User)
        return (
            sa.select(
                col(AgentAddon.id),
                col(AgentAddon.organization_id),
                col(Organization.name),
                col(AgentAddon.agent_id),
                col(Agent.name),
                col(Agent.agent_type),
                col(Agent.deleted_at).is_not(None),
                col(AgentAddon.kind),
                col(AgentAddon.name),
                col(AgentAddon.spec),
                col(AgentAddon.reason),
                col(AgentAddon.state),
                col(AgentAddon.rejection_reason),
                col(requester.full_name),
                col(requester.email),
                col(decider.full_name),
                col(decider.email),
                col(AgentAddon.created_at),
                col(AgentAddon.decided_at),
                col(AgentAddon.updated_at),
            )
            .join(Agent, col(Agent.id) == col(AgentAddon.agent_id))
            .join(Organization, col(Organization.id) == col(AgentAddon.organization_id))
            .outerjoin(requester, col(requester.id) == col(AgentAddon.requested_by_user_id))
            .outerjoin(decider, col(decider.id) == col(AgentAddon.decided_by_user_id))
        )

    def get_requester(self, addon_id: UUID) -> tuple[str, str | None] | None:
        """The requester's email and name, for telling them of a decision; None when the
        add-on or its requester is gone."""
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(User.email, User.full_name)
                .join(AgentAddon, col(AgentAddon.requested_by_user_id) == col(User.id))
                .where(col(AgentAddon.id) == addon_id)
            ).first()
        return (row[0], row[1]) if row is not None else None

    def find_notified_recipients(self, delivery_id: UUID) -> set[str]:
        with Session(self.delegate.engine) as session:
            return set(
                session.exec(
                    select(AgentAddonEmailReceipt.recipient_email).where(
                        col(AgentAddonEmailReceipt.delivery_id) == delivery_id
                    )
                ).all()
            )

    def record_recipient_notified(self, delivery_id: UUID, recipient_email: str) -> None:
        with Session(self.delegate.engine) as session:
            session.add(AgentAddonEmailReceipt(delivery_id=delivery_id, recipient_email=recipient_email))
            try:
                session.commit()
            except IntegrityError:
                # The receipt already exists, which is exactly the idempotency it records.
                session.rollback()

    @staticmethod
    def _delivery_ids(session: Session, event_ids: list[UUID]) -> list[UUID]:
        return list(session.exec(select(EventDelivery.id).where(col(EventDelivery.event_id).in_(event_ids))))
