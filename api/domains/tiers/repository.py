from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlalchemy import func, text
from sqlmodel import Session, col, select

from api.domains.agent_webhooks.models import AgentWebhook
from api.domains.agents.exceptions import AgentLimitReached
from api.domains.agents.models import Agent, AgentStatus
from api.domains.communications.models import CommunicationConnection
from api.domains.communications.transport import NATIVE_PLATFORM_KEYS
from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import (
    EVENT_REGISTRY,
    ORGANIZATION_TIER_CHANGED,
    ORGANIZATION_TIER_HOLDS_CHANGED,
    PLATFORM_TIER_CHANGED,
    PLATFORM_TIER_CREATED,
    PLATFORM_TIER_DELETED,
)
from api.domains.events.models import EventScope
from api.domains.events.repository import OutboxMessageRepository
from api.domains.organizations.models import Organization
from api.domains.tiers.models import (
    TIER_SETTINGS,
    Tier,
    TierActivation,
    TierFeature,
    TierHeldAgentRead,
    TierHeldItemRead,
    TierHoldPreviewRead,
    TierHoldsRead,
    allows_feature,
    allows_platform,
)
from api.domains.usage.models import SuspensionReason
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@dataclass(frozen=True)
class Actor:
    user_id: UUID
    display: str


@dataclass(frozen=True)
class TierWriteResult:
    tier: Tier
    # Empty when nothing changed, so there is nothing to dispatch.
    delivery_ids: list[UUID]


@dataclass(frozen=True)
class _HoldPlan:
    live: list[Agent]
    # The newest live Agents beyond the Agent Limit.
    agents: list[Agent]
    connections: list[CommunicationConnection]
    memory_agents: list[Agent]
    webhooks: list[AgentWebhook]
    kept_running: set[UUID]


@dataclass(frozen=True)
class TierHoldChange:
    """What one hold, release or Tier change put on hold or released."""

    held_agent_ids: list[UUID] = field(default_factory=list)
    released_agent_ids: list[UUID] = field(default_factory=list)
    held_connection_ids: list[UUID] = field(default_factory=list)
    held_webhook_ids: list[UUID] = field(default_factory=list)
    held_memory_agent_ids: list[UUID] = field(default_factory=list)
    # Held Agents that were running, for the caller to stop once this has committed.
    running_agent_ids: list[UUID] = field(default_factory=list)
    # Kept Agents that were running with a native Connection just held: its runtime still
    # has it until the Agent restarts, so the caller restarts them.
    restart_agent_ids: list[UUID] = field(default_factory=list)
    delivery_ids: list[UUID] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(
            self.held_agent_ids
            or self.released_agent_ids
            or self.held_connection_ids
            or self.held_webhook_ids
            or self.held_memory_agent_ids
        )


@dataclass(frozen=True)
class TierCoverage:
    """What an Organization runs that a Tier restricts."""

    agents: int
    enabled_platform_keys: frozenset[str]
    memory_agents: int
    enabled_webhooks: int


def _event_value(value: object) -> object:
    """Amounts go on audit Events as numbers, as the billing settings' do."""
    return float(value) if isinstance(value, Decimal) else value


@inject
@singleton
@dataclass
class TierRepository:
    """The Tier catalog. Every write and its audit Events commit together."""

    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    def assign_with_event(
        self,
        organization_id: UUID,
        tier: Tier | None,
        *,
        actor: ActorIdentity,
        actor_display: str,
        by_platform: bool = True,
    ) -> tuple[Organization, list[UUID]] | None:
        """Put the Organization on a Tier, or take it off any, with its audit Event in the
        same commit. No Event when nothing changed. None when the Organization does not exist.
        `by_platform` is false when a subscription chose the Tier."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            organization = session.exec(
                select(Organization).where(col(Organization.id) == organization_id).with_for_update()
            ).first()
            if organization is None:
                return None
            tier_id = tier.id if tier is not None else None
            if organization.tier_id == tier_id:
                return organization, []
            previous = session.get(Tier, organization.tier_id) if organization.tier_id is not None else None
            organization.tier_id = tier_id
            organization.tier_assigned_by_platform = by_platform and tier is not None
            organization.tier_holds_due_at = None
            organization.updated_at = datetime.now(UTC)
            session.add(organization)
            session.flush()
            event = EVENT_REGISTRY.build_event(
                event_name=ORGANIZATION_TIER_CHANGED,
                schema_version=1,
                occurred_at=datetime.now(UTC),
                organization_id=organization_id,
                actor=actor,
                subject=SubjectIdentity(
                    type=SubjectIdentityType.ORGANIZATION,
                    id=organization_id,
                    organization_id=organization_id,
                ),
                correlation_id=uuid4(),
                payload={
                    "organization_id": organization_id,
                    "tier_key": tier.key if tier is not None else None,
                    "previous_tier_key": previous.key if previous is not None else None,
                    "assigned_by_platform": by_platform,
                    "actor_display": actor_display,
                    "subject_display": organization.name,
                },
            )
            self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return organization, delivery_ids

    def list_all(self) -> list[Tier]:
        with Session(self.delegate.engine) as session:
            return list(session.exec(select(Tier).order_by(col(Tier.sort_order), col(Tier.name))).all())

    def get(self, tier_id: UUID) -> Tier | None:
        with Session(self.delegate.engine) as session:
            return session.get(Tier, tier_id)

    def list_offered(self) -> list[Tier]:
        """Tiers offered to new Organizations, in catalog order."""
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(Tier)
                    .where(col(Tier.enabled).is_(True))
                    .order_by(col(Tier.sort_order), col(Tier.price_usd), col(Tier.name))
                ).all()
            )

    def system_tier_id(self, key: str) -> UUID:
        """The id of one of the system's Tiers, which the catalog always has."""
        with Session(self.delegate.engine) as session:
            tier_id = session.exec(select(Tier.id).where(col(Tier.key) == key)).first()
        if tier_id is None:
            raise RuntimeError(f"The {key} Tier is missing from the catalog")
        return tier_id

    def for_organization(self, organization_id: UUID) -> Tier | None:
        """The Tier the Organization is on; None when it has none or does not exist."""
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(Tier)
                .join(Organization, col(Organization.tier_id) == col(Tier.id))
                .where(col(Organization.id) == organization_id)
            ).first()

    def coverage(self, organization_id: UUID) -> TierCoverage:
        """What the Organization runs that a Tier restricts, counting every live Agent."""
        with Session(self.delegate.engine) as session:
            live_agent = (col(Agent.organization_id) == organization_id) & col(Agent.deleted_at).is_(None)
            agents = (
                session.scalar(
                    select(func.count()).select_from(Agent).where(live_agent, col(Agent.suspended_at).is_(None))
                )
                or 0
            )
            memory_agents = (
                session.scalar(
                    select(func.count()).select_from(Agent).where(live_agent, col(Agent.memory_enabled).is_(True))
                )
                or 0
            )
            platform_keys = session.exec(
                select(CommunicationConnection.platform_key)
                .distinct()
                .join(Agent, col(Agent.id) == col(CommunicationConnection.agent_id))
                .where(
                    live_agent,
                    col(CommunicationConnection.enabled).is_(True),
                    col(CommunicationConnection.retired_at).is_(None),
                )
            ).all()
            webhooks = (
                session.scalar(
                    select(func.count())
                    .select_from(AgentWebhook)
                    .join(Agent, col(Agent.id) == col(AgentWebhook.agent_id))
                    .where(live_agent, col(AgentWebhook.enabled).is_(True), col(AgentWebhook.retired_at).is_(None))
                )
                or 0
            )
            return TierCoverage(
                agents=agents,
                enabled_platform_keys=frozenset(platform_keys),
                memory_agents=memory_agents,
                enabled_webhooks=webhooks,
            )

    def organizations_on(self, tier_id: UUID) -> list[UUID]:
        with Session(self.delegate.engine) as session:
            return list(session.exec(select(Organization.id).where(col(Organization.tier_id) == tier_id)).all())

    def apply_holds(
        self, organization_id: UUID, agent_limit: int, *, actor: ActorIdentity, actor_display: str
    ) -> TierHoldChange:
        """Hold whatever the Organization's Tier no longer covers, under its row lock: the newest
        Agents beyond `agent_limit` (the oldest are kept), enabled Connections on Platforms the
        Tier leaves out, and Agent Memory and Agent Webhooks without their features. Nothing is
        deleted. Without a Tier, nothing is held."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            organization = self._locked_organization(session, organization_id)
            if organization is None or organization.tier_id is None:
                return TierHoldChange()
            tier = session.get(Tier, organization.tier_id)
            assert tier is not None
            plan = self._plan_holds(session, organization_id, tier, agent_limit)
            now = datetime.now(UTC)
            change = TierHoldChange()
            for agent in plan.agents:
                agent.suspend(SuspensionReason.TIER, now)
                session.add(agent)
                change.held_agent_ids.append(agent.id)
                if agent.status == AgentStatus.RUNNING:
                    change.running_agent_ids.append(agent.id)
            for connection in plan.connections:
                connection.suspend(SuspensionReason.TIER, now)
                if (
                    connection.agent_id in plan.kept_running
                    and connection.platform_key in NATIVE_PLATFORM_KEYS
                    and connection.agent_id not in change.restart_agent_ids
                ):
                    change.restart_agent_ids.append(connection.agent_id)
                connection.revision += 1
                connection.updated_at = now
                session.add(connection)
                change.held_connection_ids.append(connection.id)
            for agent in plan.memory_agents:
                agent.suspend_memory(SuspensionReason.TIER, now)
                session.add(agent)
                change.held_memory_agent_ids.append(agent.id)
            for webhook in plan.webhooks:
                webhook.suspend(SuspensionReason.TIER, now)
                webhook.revision += 1
                webhook.updated_at = now
                session.add(webhook)
                change.held_webhook_ids.append(webhook.id)
            return self._commit_hold_change(session, organization, change, "tier", actor, actor_display)

    def preview_holds(self, organization_id: UUID, tier: Tier, agent_limit: int) -> TierHoldPreviewRead:
        """What moving the Organization to `tier` would hold now, writing nothing."""
        with Session(self.delegate.engine) as session:
            plan = self._plan_holds(session, organization_id, tier, agent_limit)
            names = {agent.id: agent.name for agent in plan.live}
            return TierHoldPreviewRead(
                tier=tier.name,
                agents=[
                    TierHeldAgentRead(id=a.id, name=a.name, status=a.status.value, suspended_at=None)
                    for a in plan.agents
                ],
                connections=[
                    TierHeldItemRead(
                        id=connection.id,
                        agent_id=connection.agent_id,
                        agent_name=names.get(connection.agent_id, ""),
                        name=connection.display_name,
                        platform_key=connection.platform_key,
                        suspended_at=None,
                    )
                    for connection in plan.connections
                ],
                webhooks=[
                    TierHeldItemRead(
                        id=webhook.id,
                        agent_id=webhook.agent_id,
                        agent_name=names.get(webhook.agent_id, ""),
                        name=webhook.display_name,
                        suspended_at=None,
                    )
                    for webhook in plan.webhooks
                ],
                memory=[
                    TierHeldItemRead(id=a.id, agent_id=a.id, agent_name=a.name, name=a.name, suspended_at=None)
                    for a in plan.memory_agents
                ],
            )

    @staticmethod
    def _plan_holds(session: Session, organization_id: UUID, tier: Tier, agent_limit: int) -> _HoldPlan:
        """What the Tier would hold among what the Organization runs and isn't held yet."""
        live = list(
            session.exec(
                select(Agent)
                .where(
                    col(Agent.organization_id) == organization_id,
                    col(Agent.deleted_at).is_(None),
                    col(Agent.suspended_at).is_(None),
                )
                .order_by(col(Agent.created_at), col(Agent.id))
            ).all()
        )
        held = live[agent_limit:]
        live_ids = [agent.id for agent in live]
        connections = [
            connection
            for connection in session.exec(
                select(CommunicationConnection).where(
                    col(CommunicationConnection.agent_id).in_(live_ids),
                    col(CommunicationConnection.enabled).is_(True),
                    col(CommunicationConnection.retired_at).is_(None),
                )
            ).all()
            if not allows_platform(tier, connection.platform_key)
        ]
        memory_agents = (
            [] if allows_feature(tier, TierFeature.AGENT_MEMORY) else [agent for agent in live if agent.memory_enabled]
        )
        webhooks = (
            []
            if allows_feature(tier, TierFeature.AGENT_WEBHOOKS)
            else list(
                session.exec(
                    select(AgentWebhook).where(
                        col(AgentWebhook.agent_id).in_(live_ids),
                        col(AgentWebhook.enabled).is_(True),
                        col(AgentWebhook.retired_at).is_(None),
                    )
                ).all()
            )
        )
        held_ids = {agent.id for agent in held}
        return _HoldPlan(
            live=live,
            agents=held,
            connections=connections,
            memory_agents=memory_agents,
            webhooks=webhooks,
            kept_running={a.id for a in live if a.id not in held_ids and a.status == AgentStatus.RUNNING},
        )

    def hold_agent(
        self, organization_id: UUID, agent_id: UUID, *, actor: ActorIdentity, actor_display: str
    ) -> TierHoldChange | None:
        """Put one Agent on hold by choice, to free its place. None when it isn't the
        Organization's live Agent."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            organization = self._locked_organization(session, organization_id)
            agent = self._live_agent(session, organization_id, agent_id)
            if organization is None or agent is None:
                return None
            change = TierHoldChange()
            if agent.suspended_at is None:
                agent.suspend(SuspensionReason.TIER, datetime.now(UTC))
                session.add(agent)
                change.held_agent_ids.append(agent.id)
                if agent.status == AgentStatus.RUNNING:
                    change.running_agent_ids.append(agent.id)
            return self._commit_hold_change(session, organization, change, "choice", actor, actor_display)

    def release_agent(
        self,
        organization_id: UUID,
        agent_id: UUID,
        agent_limit: int | None,
        *,
        actor: ActorIdentity,
        actor_display: str,
    ) -> TierHoldChange | None:
        """Release one held Agent when the Agent Limit has a place for it. None when it isn't
        the Organization's live Agent. Raises AgentLimitReached when there is no place."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            organization = self._locked_organization(session, organization_id)
            agent = self._live_agent(session, organization_id, agent_id)
            if organization is None or agent is None:
                return None
            change = TierHoldChange()
            if agent.suspension_reason == SuspensionReason.TIER:
                # The same lock a hire takes, so a release and a hire can't both take the last place.
                session.scalar(
                    text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                    {"lock_key": f"agent-limit:{organization_id}"},
                )
                counted = session.scalar(
                    select(func.count())
                    .select_from(Agent)
                    .where(
                        col(Agent.organization_id) == organization_id,
                        col(Agent.deleted_at).is_(None),
                        col(Agent.suspended_at).is_(None),
                    )
                )
                if agent_limit is not None and (counted or 0) >= agent_limit:
                    raise AgentLimitReached(agent_limit)
                agent.resume()
                session.add(agent)
                change.released_agent_ids.append(agent.id)
            return self._commit_hold_change(session, organization, change, "choice", actor, actor_display)

    def list_holds(self, organization_id: UUID) -> TierHoldsRead:
        with Session(self.delegate.engine) as session:
            live_agent = (col(Agent.organization_id) == organization_id) & col(Agent.deleted_at).is_(None)
            agents = session.exec(select(Agent).where(live_agent).order_by(col(Agent.created_at), col(Agent.id))).all()
            names = {agent.id: agent.name for agent in agents}
            connections = session.exec(
                select(CommunicationConnection)
                .join(Agent, col(Agent.id) == col(CommunicationConnection.agent_id))
                .where(
                    live_agent,
                    col(CommunicationConnection.suspension_reason) == SuspensionReason.TIER,
                    col(CommunicationConnection.retired_at).is_(None),
                )
                .order_by(col(CommunicationConnection.suspended_at))
            ).all()
            webhooks = session.exec(
                select(AgentWebhook)
                .join(Agent, col(Agent.id) == col(AgentWebhook.agent_id))
                .where(
                    live_agent,
                    col(AgentWebhook.suspension_reason) == SuspensionReason.TIER,
                    col(AgentWebhook.retired_at).is_(None),
                )
                .order_by(col(AgentWebhook.suspended_at))
            ).all()
            return TierHoldsRead(
                agents=[
                    TierHeldAgentRead(
                        id=agent.id,
                        name=agent.name,
                        status=agent.status.value,
                        suspended_at=agent.suspended_at if agent.suspension_reason == SuspensionReason.TIER else None,
                    )
                    for agent in agents
                ],
                connections=[
                    TierHeldItemRead(
                        id=connection.id,
                        agent_id=connection.agent_id,
                        agent_name=names.get(connection.agent_id, ""),
                        name=connection.display_name,
                        platform_key=connection.platform_key,
                        revision=connection.revision,
                        suspended_at=connection.suspended_at,
                    )
                    for connection in connections
                ],
                webhooks=[
                    TierHeldItemRead(
                        id=webhook.id,
                        agent_id=webhook.agent_id,
                        agent_name=names.get(webhook.agent_id, ""),
                        name=webhook.display_name,
                        revision=webhook.revision,
                        suspended_at=webhook.suspended_at,
                    )
                    for webhook in webhooks
                ],
                memory=[
                    TierHeldItemRead(
                        id=agent.id,
                        agent_id=agent.id,
                        agent_name=agent.name,
                        name=agent.name,
                        suspended_at=agent.memory_suspended_at,
                    )
                    for agent in agents
                    if agent.memory_suspension_reason == SuspensionReason.TIER and not agent.memory_enabled
                ],
            )

    @staticmethod
    def _locked_organization(session: Session, organization_id: UUID) -> Organization | None:
        return session.exec(
            select(Organization).where(col(Organization.id) == organization_id).with_for_update()
        ).first()

    @staticmethod
    def _live_agent(session: Session, organization_id: UUID, agent_id: UUID) -> Agent | None:
        return session.exec(
            select(Agent)
            .where(
                col(Agent.id) == agent_id,
                col(Agent.organization_id) == organization_id,
                col(Agent.deleted_at).is_(None),
            )
            .with_for_update()
        ).first()

    def _commit_hold_change(
        self,
        session: Session,
        organization: Organization,
        change: TierHoldChange,
        reason: str,
        actor: ActorIdentity,
        actor_display: str,
    ) -> TierHoldChange:
        if not change.changed:
            session.rollback()
            return change
        session.flush()
        event = EVENT_REGISTRY.build_event(
            event_name=ORGANIZATION_TIER_HOLDS_CHANGED,
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=organization.id,
            actor=actor,
            subject=SubjectIdentity(
                type=SubjectIdentityType.ORGANIZATION, id=organization.id, organization_id=organization.id
            ),
            correlation_id=uuid4(),
            payload={
                "organization_id": organization.id,
                "reason": reason,
                "held_agent_ids": change.held_agent_ids,
                "released_agent_ids": change.released_agent_ids,
                "held_connection_ids": change.held_connection_ids,
                "held_webhook_ids": change.held_webhook_ids,
                "held_memory_agent_ids": change.held_memory_agent_ids,
                "actor_display": actor_display,
                "subject_display": organization.name,
            },
        )
        self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
        change.delivery_ids.extend(self._delivery_ids(session, [event.event_id]))
        session.commit()
        return change

    def key_taken(self, key: str) -> bool:
        with Session(self.delegate.engine) as session:
            return session.exec(select(Tier.id).where(col(Tier.key) == key)).first() is not None

    def name_taken(self, name: str, *, excluding: UUID | None = None) -> bool:
        """Whether another Tier already has this name, ignoring case and surrounding space."""
        with Session(self.delegate.engine) as session:
            query = select(Tier.id).where(func.lower(col(Tier.name)) == name.strip().lower())
            if excluding is not None:
                query = query.where(col(Tier.id) != excluding)
            return session.exec(query).first() is not None

    def create_with_event(self, tier: Tier, *, actor: Actor) -> TierWriteResult:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            session.add(tier)
            session.flush()
            event_id = self._stage(session, PLATFORM_TIER_CREATED, tier, actor, self._values(tier), uuid4())
            delivery_ids = self._delivery_ids(session, [event_id])
            session.commit()
            session.refresh(tier)
            return TierWriteResult(tier=tier, delivery_ids=delivery_ids)

    def update_with_events(
        self, tier_id: UUID, changes: Mapping[str, object], *, actor: Actor
    ) -> TierWriteResult | None:
        """Apply the changes and record one change Event per setting that moved, under the
        Tier's row lock. A value equal to the stored one records nothing. Returns None when
        the Tier does not exist."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            tier = session.get(Tier, tier_id, with_for_update=True)
            if tier is None:
                return None
            moved: list[tuple[str, object, object]] = []
            for setting in TIER_SETTINGS:
                if setting not in changes:
                    continue
                previous, current = getattr(tier, setting), changes[setting]
                if previous != current:
                    setattr(tier, setting, current)
                    moved.append((setting, previous, current))
            if not moved:
                return TierWriteResult(tier=tier, delivery_ids=[])

            session.add(tier)
            session.flush()
            correlation_id = uuid4()
            event_ids = [
                self._stage(
                    session,
                    PLATFORM_TIER_CHANGED,
                    tier,
                    actor,
                    {"setting": setting, "previous": _event_value(previous), "current": _event_value(current)},
                    correlation_id,
                )
                for setting, previous, current in moved
            ]
            delivery_ids = self._delivery_ids(session, event_ids)
            session.commit()
            session.refresh(tier)
            return TierWriteResult(tier=tier, delivery_ids=delivery_ids)

    def delete_with_event(self, tier_id: UUID, *, actor: Actor) -> TierWriteResult | None:
        """Delete a Tier and record it. Returns None when the Tier does not exist."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            tier = session.get(Tier, tier_id, with_for_update=True)
            if tier is None:
                return None
            event_id = self._stage(session, PLATFORM_TIER_DELETED, tier, actor, self._values(tier), uuid4())
            delivery_ids = self._delivery_ids(session, [event_id])
            session.delete(tier)
            session.commit()
            return TierWriteResult(tier=tier, delivery_ids=delivery_ids)

    @staticmethod
    def _values(tier: Tier) -> dict[str, object]:
        return {
            "key": tier.key,
            "activation": TierActivation(tier.activation).value,
            **{setting: _event_value(getattr(tier, setting)) for setting in TIER_SETTINGS if setting != "name"},
        }

    def _stage(
        self,
        session: Session,
        event_name: str,
        tier: Tier,
        actor: Actor,
        payload: Mapping[str, object],
        correlation_id: UUID,
    ) -> UUID:
        event = EVENT_REGISTRY.build_event(
            event_name=event_name,
            schema_version=1,
            occurred_at=datetime.now(UTC),
            event_scope=EventScope.PLATFORM,
            organization_id=None,
            actor=ActorIdentity(type=ActorIdentityType.USER, id=actor.user_id),
            subject=SubjectIdentity(type=SubjectIdentityType.SYSTEM, id=tier.id),
            correlation_id=correlation_id,
            payload={
                "actor_user_id": actor.user_id,
                "actor_display": actor.display,
                "subject_display": tier.name,
                **payload,
            },
        )
        self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
        return event.event_id

    @staticmethod
    def _delivery_ids(session: Session, event_ids: list[UUID]) -> list[UUID]:
        return list(session.exec(select(EventDelivery.id).where(col(EventDelivery.event_id).in_(event_ids))))
