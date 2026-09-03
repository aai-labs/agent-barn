from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy import exists, func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.agents.models import (
    Agent,
    AgentAccess,
    AgentFilter,
    AgentLifecycleEmailReceipt,
    AgentLogSnapshot,
    AgentSecret,
    AgentSkill,
    AgentStatus,
    SecretProvider,
)
from api.domains.communications.email_address_repository import release_agent_email_addresses
from api.domains.communications.models import (
    AgentEmailAddress,
    CommunicationConnection,
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    CommunicationPlatform,
)
from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import (
    AGENT_ACCESS_GRANTED,
    AGENT_ACCESS_REVOKED,
    AGENT_CREATED,
    AGENT_DELETED,
    AGENT_GENERAL_ACCESS_CHANGED,
    AGENT_SECRET_ADDED,
    AGENT_SECRET_REMOVED,
    AGENT_UPDATED,
    EVENT_REGISTRY,
)
from api.domains.events.repository import OutboxMessageRepository
from api.domains.platform_admin.models import StatsGranularity
from api.domains.rbac.catalog import (
    AGENT_OWNER_ROLE_ID,
    PERMISSION_ID_BY_KEY,
    PermissionKey,
)
from api.domains.rbac.models import (
    AgentAccessRole,
    AgentAccessRolePermission,
    Permission,
)
from api.domains.rbac.policy import AuthorizationScope
from api.domains.users.models import User
from api.domains.users.organization_users.models import OrganizationUser
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import Pagination


@dataclass(frozen=True)
class AgentLifecycleEventResult:
    agent: Agent
    delivery_ids: list[UUID]


@dataclass(frozen=True)
class AgentLifecycleEmailRecipient:
    email: str
    full_name: str | None


def agent_scope_predicates(authorization_scope: AuthorizationScope, *, include_deleted: bool = False):
    """SQL predicates for implicit Organization or explicit Agent visibility."""
    predicates = [
        col(Agent.organization_id) == authorization_scope.organization_id,
    ]
    if not include_deleted:
        predicates.append(col(Agent.deleted_at).is_(None))
    if authorization_scope.membership_id is not None:
        if authorization_scope.permission is None:
            raise ValueError("Explicit Agent visibility requires a Permission")
        direct_access = exists().where(
            col(AgentAccess.agent_id) == col(Agent.id),
            col(AgentAccess.organization_id) == authorization_scope.organization_id,
            col(AgentAccess.membership_id) == authorization_scope.membership_id,
            col(AgentAccessRolePermission.role_id) == col(AgentAccess.access_role_id),
            col(AgentAccessRolePermission.permission_id) == PERMISSION_ID_BY_KEY[authorization_scope.permission],
        )
        if authorization_scope.include_general_access:
            general_access = exists().where(
                col(AgentAccessRolePermission.role_id) == col(Agent.general_access_role_id),
                col(AgentAccessRolePermission.permission_id) == PERMISSION_ID_BY_KEY[authorization_scope.permission],
            )
            predicates.append(or_(direct_access, general_access))
        else:
            predicates.append(direct_access)
    return tuple(predicates)


@inject
@singleton
@dataclass
class AgentRepository:
    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    def get_by_id(self, agent_id: UUID) -> Agent | None:
        with Session(self.delegate.engine) as session:
            query = select(Agent).where(col(Agent.id) == agent_id).where(col(Agent.deleted_at).is_(None))
            return session.exec(query).first()

    def get_active_in_scope(self, agent_id: UUID, authorization_scope: AuthorizationScope) -> Agent | None:
        with Session(self.delegate.engine) as session:
            query = select(Agent).where(
                col(Agent.id) == agent_id,
                *agent_scope_predicates(authorization_scope),
            )
            return session.exec(query).first()

    def get_deleted_in_scope(self, agent_id: UUID, authorization_scope: AuthorizationScope) -> Agent | None:
        if not authorization_scope.has_organization_visibility:
            return None
        with Session(self.delegate.engine) as session:
            query = select(Agent).where(
                col(Agent.id) == agent_id,
                col(Agent.deleted_at).is_not(None),
                *agent_scope_predicates(authorization_scope, include_deleted=True),
            )
            return session.exec(query).first()

    def count_active_by_org(self, org_id: UUID) -> int:
        with Session(self.delegate.engine) as session:
            count_query = (
                select(func.count())
                .select_from(Agent)
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.deleted_at).is_(None))
            )
            return session.scalar(count_query) or 0

    def count_by_model_source(self, org_id: UUID) -> tuple[int, int]:
        """(inheriting, override) Agent counts for the Organization's Agent Settings.

        Deliberately unscoped by Agent visibility: the caller holds
        `organization.update`, and these two numbers state how far a default-model
        change reaches rather than naming any Agent the caller may not see.
        An empty `model` is the inherit sentinel.
        """
        with Session(self.delegate.engine) as session:
            inheriting, override = session.exec(
                select(
                    func.count().filter(col(Agent.model) == ""),
                    func.count().filter(col(Agent.model) != ""),
                )
                .select_from(Agent)
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.deleted_at).is_(None))
            ).one()
            return int(inheriting or 0), int(override or 0)

    def list_pinned_models(self, org_id: UUID) -> list[tuple[str, str]]:
        """(name, model) for every Agent in the Organization holding an explicit model.

        Backs the allowlist guard: removing a model that an Agent names would not move
        that Agent, it would only make it unstartable, so the caller has to be told
        which Agents stand in the way. Unscoped by Agent visibility for the same reason
        as `count_by_model_source` — but this one names Agents, so callers must hold
        `organization.update`.
        """
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(col(Agent.name), col(Agent.model))
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.deleted_at).is_(None))
                .where(col(Agent.model) != "")
                .order_by(col(Agent.name))
            ).all()
            return [(name, model) for name, model in rows]

    def count_agents_in_error(self) -> int:
        """All-orgs aggregate count for the /metrics probe (agents_in_error
        gauge). Deliberately unscoped and deliberately narrow: it returns a
        single number and must never back user-facing data — org-scoped
        queries go through AuthorizationScope like everything else."""
        with Session(self.delegate.engine) as session:
            count_query = (
                select(func.count())
                .select_from(Agent)
                .where(col(Agent.status) == AgentStatus.ERROR)
                .where(col(Agent.deleted_at).is_(None))
            )
            return session.scalar(count_query) or 0

    def _stats_predicates(
        self,
        organization_id: UUID | None,
        agent_id: UUID | None,
        created_by_user_id: UUID | None,
        platform: CommunicationPlatform | None,
    ) -> list[Any]:
        """Shared narrowing for the stats aggregates (AF-256). Deliberately does
        not include a deleted_at predicate — callers decide that, since inventory
        over time has to see Agents that were later deleted."""
        predicates: list[Any] = []
        if organization_id is not None:
            predicates.append(col(Agent.organization_id) == organization_id)
        if agent_id is not None:
            predicates.append(col(Agent.id) == agent_id)
        if created_by_user_id is not None:
            predicates.append(col(Agent.created_by_user_id) == created_by_user_id)
        if platform is not None:
            predicates.append(
                exists().where(
                    col(CommunicationConnection.agent_id) == col(Agent.id),
                    col(CommunicationConnection.platform_key) == platform.value,
                    col(CommunicationConnection.retired_at).is_(None),
                )
            )
        return predicates

    def count_agents_for_stats(
        self,
        *,
        organization_id: UUID | None = None,
        agent_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
        platform: CommunicationPlatform | None = None,
    ) -> tuple[int, int, int, int]:
        """(total, running, stopped, errored) Agent counts for the stats
        surfaces (AF-256).

        Unscoped by default and only ever reached through
        `require_platform_admin`, like `count_agents_in_error`; org-scoped reads
        keep using AuthorizationScope. `organization_id` narrows the same
        aggregate so a future Organization dashboard reuses this query.

        Every number composes with `deleted_at IS NULL`, so a soft-deleted Agent
        whose status was never transitioned cannot inflate any of them. The
        three status counts partition `total`, since AgentStatus has exactly
        these three values.
        """
        predicates = self._stats_predicates(organization_id, agent_id, created_by_user_id, platform)
        live = [col(Agent.deleted_at).is_(None), *predicates]
        with Session(self.delegate.engine) as session:
            total, running, stopped, errored = session.exec(
                select(
                    func.count(),
                    func.count().filter(col(Agent.status) == AgentStatus.RUNNING),
                    func.count().filter(col(Agent.status) == AgentStatus.STOPPED),
                    func.count().filter(col(Agent.status) == AgentStatus.ERROR),
                )
                .select_from(Agent)
                .where(*live)
            ).one()
            return int(total or 0), int(running or 0), int(stopped or 0), int(errored or 0)

    def agent_inventory_since(
        self,
        window_start: datetime,
        window_end: datetime,
        *,
        unit: StatsGranularity = StatsGranularity.DAY,
        organization_id: UUID | None = None,
        agent_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
        platform: CommunicationPlatform | None = None,
    ) -> list[tuple[datetime, int, int]]:
        """(bucket_start, existing, created) Agent inventory for the stats
        surfaces (AF-256), reconstructed exactly from created_at/deleted_at.

        `existing` counts Agents live at the end of each bucket: created on or
        before it, and either never deleted or deleted after it. That is why the
        deleted_at predicate cannot live in `_stats_predicates` — an Agent
        deleted last week still existed in the buckets before.

        `unit` is a postgres date_trunc unit ('hour' | 'day' | 'week'), chosen
        from the window span so a one-day window is not a single bar and a
        two-year one is not seven hundred. It also drives the generate_series
        step, so the empty buckets are filled in at the same resolution.
        """
        predicates = self._stats_predicates(organization_id, agent_id, created_by_user_id, platform)
        step = sa.text(f"interval '1 {unit.value}'")
        created_utc = sa.func.timezone("UTC", col(Agent.created_at))
        deleted_utc = sa.func.timezone("UTC", col(Agent.deleted_at))

        with Session(self.delegate.engine) as session:
            buckets = select(
                func.generate_series(
                    func.date_trunc(unit.value, sa.func.timezone("UTC", sa.literal(window_start))),
                    func.date_trunc(unit.value, sa.func.timezone("UTC", sa.literal(window_end))),
                    step,
                ).label("bucket")
            ).subquery()
            bucket_col = buckets.c.bucket

            # Inventory is a running total, not a per-bucket recount. Joining
            # every Agent to every bucket and counting the survivors is
            # O(buckets x agents) — 721 hourly buckets over 300 Agents already
            # materialises 200k rows, and it grows with both the window and the
            # fleet. Instead: how many were alive when the window opened, plus
            # creations minus deletions as we walk forward.
            alive_at_start = (
                select(func.count())
                .select_from(Agent)
                .where(
                    col(Agent.created_at) < window_start,
                    sa.or_(col(Agent.deleted_at).is_(None), col(Agent.deleted_at) >= window_start),
                    *predicates,
                )
                .scalar_subquery()
            )

            created_per_bucket = (
                select(
                    func.date_trunc(unit.value, created_utc).label("bucket"),
                    func.count().label("created"),
                )
                .where(
                    col(Agent.created_at) >= window_start,
                    col(Agent.created_at) < window_end,
                    *predicates,
                )
                .group_by(sa.text("1"))
                .subquery()
            )

            deleted_per_bucket = (
                select(
                    func.date_trunc(unit.value, deleted_utc).label("bucket"),
                    func.count().label("deleted"),
                )
                .where(
                    col(Agent.deleted_at).is_not(None),
                    col(Agent.deleted_at) >= window_start,
                    col(Agent.deleted_at) < window_end,
                    *predicates,
                )
                .group_by(sa.text("1"))
                .subquery()
            )

            created = func.coalesce(created_per_bucket.c.created, 0)
            deleted = func.coalesce(deleted_per_bucket.c.deleted, 0)
            running = func.sum(created - deleted).over(order_by=bucket_col)

            query = (
                select(
                    sa.func.timezone("UTC", bucket_col).label("bucket"),
                    (alive_at_start + running).label("existing"),
                    created.label("created"),
                )
                .select_from(buckets)
                .outerjoin(created_per_bucket, created_per_bucket.c.bucket == bucket_col)
                .outerjoin(deleted_per_bucket, deleted_per_bucket.c.bucket == bucket_col)
                .order_by(bucket_col)
            )
            rows = session.exec(query).all()  # type: ignore[call-overload]
            return [(row[0], int(row[1]), int(row[2])) for row in rows]

    def find_all_active(
        self,
        authorization_scope: AuthorizationScope,
        agent_filter: AgentFilter,
        pagination: Pagination,
    ) -> tuple[list[Agent], int]:
        with Session(self.delegate.engine) as session:
            visibility = agent_scope_predicates(authorization_scope)
            query = select(Agent).where(*visibility)
            count_query = select(func.count()).select_from(Agent).where(*visibility)

            if agent_filter.status is not None:
                status_filter = col(Agent.status) == agent_filter.status
                query = query.where(status_filter)
                count_query = count_query.where(status_filter)

            total = session.scalar(count_query) or 0
            query = (
                query.order_by(col(Agent.created_at).asc())
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            )
            return list(session.exec(query).all()), total

    def get_active_communication_platforms_for_agents(
        self,
        agent_ids: list[UUID],
        authorization_scope: AuthorizationScope,
    ) -> dict[UUID, list[str]]:
        """Return distinct active Connection platform keys for visible Agents.

        The visibility predicates remain in this repository query so the
        decorative Agent projection cannot disclose a hidden Connection.
        """
        if not agent_ids:
            return {}
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(CommunicationConnection.agent_id, CommunicationConnection.platform_key)
                .join(Agent, col(Agent.id) == col(CommunicationConnection.agent_id))
                .where(
                    col(CommunicationConnection.agent_id).in_(agent_ids),
                    col(CommunicationConnection.retired_at).is_(None),
                    *agent_scope_predicates(authorization_scope),
                )
                .distinct()
                .order_by(col(CommunicationConnection.agent_id), col(CommunicationConnection.platform_key))
            ).all()
        platforms: dict[UUID, list[str]] = {agent_id: [] for agent_id in agent_ids}
        for agent_id, platform_key in rows:
            platforms[agent_id].append(platform_key)
        return platforms

    def find_agent_permissions(
        self,
        membership_id: UUID,
        organization_id: UUID,
        agent_ids: list[UUID],
        *,
        include_general_access: bool = True,
    ) -> dict[UUID, set[PermissionKey]]:
        if not agent_ids:
            return {}
        with Session(self.delegate.engine) as session:
            direct_rows = session.exec(
                select(AgentAccess.agent_id, Permission.key)
                .join(
                    AgentAccessRolePermission,
                    col(AgentAccessRolePermission.role_id) == col(AgentAccess.access_role_id),
                )
                .join(
                    Permission,
                    col(Permission.id) == col(AgentAccessRolePermission.permission_id),
                )
                .where(
                    col(AgentAccess.membership_id) == membership_id,
                    col(AgentAccess.organization_id) == organization_id,
                    col(AgentAccess.agent_id).in_(agent_ids),
                )
            ).all()
            general_rows = []
            if include_general_access:
                general_rows = session.exec(
                    select(Agent.id, Permission.key)
                    .join(
                        AgentAccessRolePermission,
                        col(AgentAccessRolePermission.role_id) == col(Agent.general_access_role_id),
                    )
                    .join(
                        Permission,
                        col(Permission.id) == col(AgentAccessRolePermission.permission_id),
                    )
                    .where(
                        col(Agent.organization_id) == organization_id,
                        col(Agent.id).in_(agent_ids),
                        col(Agent.deleted_at).is_(None),
                        col(Agent.general_access_role_id).is_not(None),
                    )
                ).all()
        permissions: dict[UUID, set[PermissionKey]] = {}
        for agent_id, key in [*direct_rows, *general_rows]:
            permissions.setdefault(agent_id, set()).add(PermissionKey(key))
        return permissions

    def replace_access_settings(
        self,
        agent_id: UUID,
        organization_id: UUID,
        *,
        general_access_role_id: UUID | None,
        assignment_roles: dict[UUID, UUID],
        actor: ActorIdentity | None = None,
        actor_display: str | None = None,
        correlation_id: UUID | None = None,
    ) -> list[UUID] | None:
        """Replace General Access and explicit assignments atomically. Returns the
        staged Event Deliveries' ids, or None if the agent/members were not found."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            agent = session.exec(
                select(Agent)
                .where(
                    col(Agent.id) == agent_id,
                    col(Agent.organization_id) == organization_id,
                    col(Agent.deleted_at).is_(None),
                )
                .with_for_update()
            ).first()
            if agent is None:
                return None

            desired_role_ids = set(assignment_roles.values())
            if general_access_role_id is not None:
                desired_role_ids.add(general_access_role_id)
            if desired_role_ids:
                existing_role_ids = set(
                    session.exec(
                        select(AgentAccessRole.id)
                        .where(
                            col(AgentAccessRole.id).in_(desired_role_ids),
                            or_(
                                col(AgentAccessRole.is_system).is_(True),
                                col(AgentAccessRole.organization_id) == organization_id,
                            ),
                        )
                        .with_for_update()
                    ).all()
                )
                if existing_role_ids != desired_role_ids:
                    return None

            if assignment_roles:
                existing_membership_ids = set(
                    session.exec(
                        select(OrganizationUser.id)
                        .where(
                            col(OrganizationUser.id).in_(set(assignment_roles)),
                            col(OrganizationUser.organization_id) == organization_id,
                        )
                        .with_for_update()
                    ).all()
                )
                if existing_membership_ids != set(assignment_roles):
                    return None

            previous_general_access_role_id = agent.general_access_role_id
            agent.general_access_role_id = general_access_role_id
            session.add(agent)

            existing_access = session.exec(
                select(AgentAccess)
                .where(
                    col(AgentAccess.agent_id) == agent_id,
                    col(AgentAccess.organization_id) == organization_id,
                )
                .with_for_update()
            ).all()
            existing_by_membership = {access.membership_id: access for access in existing_access}
            desired_membership_ids = set(assignment_roles)
            audit_actor = actor or ActorIdentity(type=ActorIdentityType.SYSTEM, id="system")
            audit_actor_display = actor_display or audit_actor.type.value
            audit_correlation_id = correlation_id or uuid4()
            staged_event_ids: list[UUID] = []

            # Snapshot each touched member's display name at write time — the same
            # pattern used for organization.member.*/ownership_transferred — so
            # `agent.access.granted`/`.revoked` remain readable after the membership
            # or user row is later deleted, without a live join at read time.
            touched_membership_ids = set(existing_by_membership) | set(assignment_roles)
            member_display_by_membership_id: dict[UUID, str] = {}
            if touched_membership_ids:
                for membership_id, full_name, email in session.exec(
                    select(OrganizationUser.id, User.full_name, User.email)
                    .join(User, col(User.id) == col(OrganizationUser.user_id))
                    .where(col(OrganizationUser.id).in_(touched_membership_ids))
                ).all():
                    member_display_by_membership_id[membership_id] = full_name or str(email)

            if previous_general_access_role_id != general_access_role_id:
                general_access_event = EVENT_REGISTRY.build_event(
                    event_name=AGENT_GENERAL_ACCESS_CHANGED,
                    schema_version=1,
                    occurred_at=datetime.now(UTC),
                    organization_id=organization_id,
                    actor=audit_actor,
                    subject=SubjectIdentity(
                        type=SubjectIdentityType.AGENT, id=agent_id, organization_id=organization_id
                    ),
                    correlation_id=audit_correlation_id,
                    payload={
                        "organization_id": organization_id,
                        "agent_id": agent_id,
                        "previous_access_role_id": previous_general_access_role_id,
                        "new_access_role_id": general_access_role_id,
                        "actor_display": audit_actor_display,
                        "subject_display": agent.name,
                    },
                )
                self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=general_access_event)
                staged_event_ids.append(general_access_event.event_id)

            for membership_id, access in existing_by_membership.items():
                if membership_id not in desired_membership_ids:
                    access_revoked_event = EVENT_REGISTRY.build_event(
                        event_name=AGENT_ACCESS_REVOKED,
                        schema_version=1,
                        occurred_at=datetime.now(UTC),
                        organization_id=organization_id,
                        actor=audit_actor,
                        subject=SubjectIdentity(
                            type=SubjectIdentityType.AGENT, id=agent_id, organization_id=organization_id
                        ),
                        correlation_id=audit_correlation_id,
                        payload={
                            "organization_id": organization_id,
                            "agent_id": agent_id,
                            "membership_id": membership_id,
                            "previous_access_role_id": access.access_role_id,
                            "actor_display": audit_actor_display,
                            "subject_display": agent.name,
                            "member_display": member_display_by_membership_id.get(membership_id, str(membership_id)),
                        },
                    )
                    self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=access_revoked_event)
                    staged_event_ids.append(access_revoked_event.event_id)
                    session.delete(access)

            for membership_id, access_role_id in assignment_roles.items():
                access = existing_by_membership.get(membership_id)
                if access is None:
                    session.add(
                        AgentAccess(
                            organization_id=organization_id,
                            membership_id=membership_id,
                            agent_id=agent_id,
                            access_role_id=access_role_id,
                        )
                    )
                    access_granted_event = EVENT_REGISTRY.build_event(
                        event_name=AGENT_ACCESS_GRANTED,
                        schema_version=1,
                        occurred_at=datetime.now(UTC),
                        organization_id=organization_id,
                        actor=audit_actor,
                        subject=SubjectIdentity(
                            type=SubjectIdentityType.AGENT, id=agent_id, organization_id=organization_id
                        ),
                        correlation_id=audit_correlation_id,
                        payload={
                            "organization_id": organization_id,
                            "agent_id": agent_id,
                            "membership_id": membership_id,
                            "access_role_id": access_role_id,
                            "actor_display": audit_actor_display,
                            "subject_display": agent.name,
                            "member_display": member_display_by_membership_id.get(membership_id, str(membership_id)),
                        },
                    )
                    self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=access_granted_event)
                    staged_event_ids.append(access_granted_event.event_id)
                elif access.access_role_id != access_role_id:
                    previous_access_role_id = access.access_role_id
                    access.access_role_id = access_role_id
                    session.add(access)
                    access_role_changed_event = EVENT_REGISTRY.build_event(
                        event_name=AGENT_ACCESS_GRANTED,
                        schema_version=1,
                        occurred_at=datetime.now(UTC),
                        organization_id=organization_id,
                        actor=audit_actor,
                        subject=SubjectIdentity(
                            type=SubjectIdentityType.AGENT, id=agent_id, organization_id=organization_id
                        ),
                        correlation_id=audit_correlation_id,
                        payload={
                            "organization_id": organization_id,
                            "agent_id": agent_id,
                            "membership_id": membership_id,
                            "access_role_id": access_role_id,
                            "previous_access_role_id": previous_access_role_id,
                            "actor_display": audit_actor_display,
                            "subject_display": agent.name,
                            "member_display": member_display_by_membership_id.get(membership_id, str(membership_id)),
                        },
                    )
                    self.outbox_repository.stage(
                        session=session, registry=EVENT_REGISTRY, event=access_role_changed_event
                    )
                    staged_event_ids.append(access_role_changed_event.event_id)

            delivery_ids = (
                list(session.exec(select(EventDelivery.id).where(col(EventDelivery.event_id).in_(staged_event_ids))))
                if staged_event_ids
                else []
            )
            session.commit()
            return delivery_ids

    def create_with_creator_access(
        self,
        agent: Agent,
        membership_id: UUID | None,
        *,
        actor: ActorIdentity,
        correlation_id: UUID | None = None,
        secrets: list[AgentSecret] | None = None,
        skills: list[AgentSkill] | None = None,
        actor_display: str | None = None,
    ) -> AgentLifecycleEventResult:
        """Create an Agent and its initial resources in one transaction.

        The LiteLLM key is allocated immediately before this method is called.
        Keeping the Agent, access row, initial secrets, skills, and their outbox
        deliveries in one transaction means a failure cannot leave a persisted
        Agent pointing at a key that create-agent compensation has deleted.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            session.add(agent)
            session.flush()
            if membership_id is not None:
                session.add(
                    AgentAccess(
                        organization_id=agent.organization_id,
                        membership_id=membership_id,
                        agent_id=agent.id,
                        access_role_id=AGENT_OWNER_ROLE_ID,
                    )
                )
            event = EVENT_REGISTRY.build_event(
                event_name=AGENT_CREATED,
                schema_version=1,
                occurred_at=datetime.now(UTC),
                organization_id=agent.organization_id,
                actor=actor,
                subject=SubjectIdentity(
                    type=SubjectIdentityType.AGENT,
                    id=agent.id,
                    organization_id=agent.organization_id,
                ),
                correlation_id=correlation_id or uuid4(),
                payload={
                    "organization_id": agent.organization_id,
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "runtime": agent.agent_type,
                    "created_by_user_id": agent.created_by_user_id,
                },
            )
            self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))

            for secret in secrets or []:
                delivery_ids.extend(
                    self._stage_secret_with_event(
                        session,
                        secret,
                        event_name=AGENT_SECRET_ADDED,
                        organization_id=agent.organization_id,
                        agent_name=agent.name,
                        actor=actor,
                        actor_display=actor_display,
                    )
                )

            if skills:
                session.add_all(skills)
                session.flush()

            # Refresh before commit so the returned object retains the same
            # behavior as the previous create method without doing fallible
            # database work after the transaction has committed.
            session.refresh(agent)
            session.commit()
            return AgentLifecycleEventResult(agent=agent, delivery_ids=delivery_ids)

    def save_with_lifecycle_event(
        self,
        agent: Agent,
        *,
        event_name: str,
        actor: ActorIdentity,
        previous_status: str,
        new_status: str,
        correlation_id: UUID | None = None,
    ) -> AgentLifecycleEventResult:
        return self._record_agent_event(
            agent,
            event_name=event_name,
            actor=actor,
            correlation_id=correlation_id,
            previous_status=previous_status,
            new_status=new_status,
        )

    def _record_agent_event(
        self,
        agent: Agent,
        *,
        event_name: str,
        actor: ActorIdentity,
        correlation_id: UUID | None,
        previous_status: str | None,
        new_status: str | None,
    ) -> AgentLifecycleEventResult:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            persisted = session.exec(
                select(Agent)
                .where(
                    col(Agent.id) == agent.id,
                    col(Agent.organization_id) == agent.organization_id,
                    col(Agent.deleted_at).is_(None),
                )
                .with_for_update()
            ).first()
            if persisted is None:
                return AgentLifecycleEventResult(agent=agent, delivery_ids=[])
            # Only the fields a lifecycle transition owns are copied onto the locked row,
            # so a concurrent edit elsewhere is not clobbered by this caller's stale copy.
            # Anything start/stop writes has to be listed here or it is silently dropped.
            persisted.status = agent.status
            persisted.last_error = agent.last_error
            persisted.ingest_key_encrypted = agent.ingest_key_encrypted
            persisted.running_model = agent.running_model
            persisted.communication_key_encrypted = agent.communication_key_encrypted
            session.add(persisted)
            session.flush()
            payload: dict[str, Any] = {
                "organization_id": persisted.organization_id,
                "agent_id": persisted.id,
                "agent_name": persisted.name,
                "runtime": persisted.agent_type,
            }
            if event_name == AGENT_CREATED:
                payload["created_by_user_id"] = persisted.created_by_user_id
            else:
                payload["previous_status"] = previous_status
                payload["new_status"] = new_status
            event = EVENT_REGISTRY.build_event(
                event_name=event_name,
                schema_version=1,
                occurred_at=datetime.now(UTC),
                organization_id=persisted.organization_id,
                actor=actor,
                subject=SubjectIdentity(
                    type=SubjectIdentityType.AGENT,
                    id=persisted.id,
                    organization_id=persisted.organization_id,
                ),
                correlation_id=correlation_id or uuid4(),
                payload=payload,
            )
            self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return AgentLifecycleEventResult(agent=persisted, delivery_ids=delivery_ids)

    _UPDATE_TRACKED_FIELDS: ClassVar[tuple[str, ...]] = (
        "name",
        "model",
        "approval_mode",
        "agent_template_id",
        "platform_template_id",
    )

    def update_scalar_fields_with_event(
        self,
        agent: Agent,
        *,
        actor: ActorIdentity,
        actor_display: str | None = None,
        correlation_id: UUID | None = None,
    ) -> AgentLifecycleEventResult:
        """Persist the scalar identity/config fields `update_agent` mutates directly
        on the Agent row (name, model, approval_mode, template pin), diffing against
        the currently-persisted row and staging an `agent.updated` event only when a
        tracked field actually changed. Skills, secrets, and nested platform config
        (Slack/Telegram/Discord) are covered by their own events elsewhere and are
        deliberately excluded from this diff."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            persisted = session.exec(
                select(Agent)
                .where(
                    col(Agent.id) == agent.id,
                    col(Agent.organization_id) == agent.organization_id,
                )
                .with_for_update()
            ).first()
            if persisted is None:
                return AgentLifecycleEventResult(agent=agent, delivery_ids=[])
            field_changes: dict[str, dict[str, Any]] = {}
            for field in self._UPDATE_TRACKED_FIELDS:
                previous_value = getattr(persisted, field)
                new_value = getattr(agent, field)
                if previous_value != new_value:
                    field_changes[field] = {"previous": previous_value, "new": new_value}
                    setattr(persisted, field, new_value)
            session.add(persisted)
            session.flush()
            if not field_changes:
                session.commit()
                return AgentLifecycleEventResult(agent=persisted, delivery_ids=[])
            event = EVENT_REGISTRY.build_event(
                event_name=AGENT_UPDATED,
                schema_version=1,
                occurred_at=datetime.now(UTC),
                organization_id=persisted.organization_id,
                actor=actor,
                subject=SubjectIdentity(
                    type=SubjectIdentityType.AGENT,
                    id=persisted.id,
                    organization_id=persisted.organization_id,
                ),
                correlation_id=correlation_id or uuid4(),
                payload={
                    "organization_id": persisted.organization_id,
                    "agent_id": persisted.id,
                    "field_changes": field_changes,
                    "actor_display": actor_display or actor.type.value,
                    "subject_display": persisted.name,
                },
            )
            self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return AgentLifecycleEventResult(agent=persisted, delivery_ids=delivery_ids)

    def soft_delete_with_event(
        self,
        agent: Agent,
        *,
        actor: ActorIdentity,
        actor_display: str | None = None,
        correlation_id: UUID | None = None,
    ) -> AgentLifecycleEventResult:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            persisted = session.exec(select(Agent).where(col(Agent.id) == agent.id).with_for_update()).first()
            if persisted is None:
                return AgentLifecycleEventResult(agent=agent, delivery_ids=[])
            now = datetime.now(UTC)
            persisted.deleted_at = now
            session.add(persisted)
            session.flush()
            # Agent deletion is a soft delete, so the database FK cascade does
            # not retire the Agent-owned Communication Connections. Release
            # their provider credentials in this same transaction so retired
            # Agents cannot keep global platform identities reserved.
            session.exec(
                sa.update(CommunicationConnection)
                .where(
                    col(CommunicationConnection.agent_id) == persisted.id,
                    col(CommunicationConnection.organization_id) == persisted.organization_id,
                    col(CommunicationConnection.retired_at).is_(None),
                )
                .values(
                    enabled=False,
                    observed_status=None,
                    credentials_encrypted="",
                    driver_key_encrypted="",
                    credential_fingerprint=None,
                    credential_scope_key=None,
                    ingress_lease_owner=None,
                    ingress_lease_expires_at=None,
                    retired_at=now,
                    updated_at=now,
                    revision=col(CommunicationConnection.revision) + 1,
                )
            )
            session.exec(
                sa.update(CommunicationDelivery)
                .where(
                    col(CommunicationDelivery.agent_id) == persisted.id,
                    col(CommunicationDelivery.organization_id) == persisted.organization_id,
                    col(CommunicationDelivery.status).in_(
                        [CommunicationDeliveryStatus.PENDING, CommunicationDeliveryStatus.PROCESSING]
                    ),
                )
                .values(
                    status=CommunicationDeliveryStatus.CANCELLED,
                    completed_at=now,
                    lease_expires_at=None,
                    last_error_code="CONNECTION_RETIRED",
                    last_error_message="Communication Connection was retired",
                )
            )
            session.exec(release_agent_email_addresses(now).where(col(AgentEmailAddress.agent_id) == persisted.id))
            event = EVENT_REGISTRY.build_event(
                event_name=AGENT_DELETED,
                schema_version=1,
                occurred_at=datetime.now(UTC),
                organization_id=persisted.organization_id,
                actor=actor,
                subject=SubjectIdentity(
                    type=SubjectIdentityType.AGENT,
                    id=persisted.id,
                    organization_id=persisted.organization_id,
                ),
                correlation_id=correlation_id or uuid4(),
                payload={
                    "organization_id": persisted.organization_id,
                    "agent_id": persisted.id,
                    "agent_name": persisted.name,
                    "runtime": persisted.agent_type,
                    "actor_display": actor_display or actor.type.value,
                    "subject_display": persisted.name,
                },
            )
            self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return AgentLifecycleEventResult(agent=persisted, delivery_ids=delivery_ids)

    def _stage_secret_with_event(
        self,
        session: Session,
        secret: AgentSecret,
        *,
        event_name: str,
        organization_id: UUID,
        agent_name: str,
        actor: ActorIdentity,
        actor_display: str | None = None,
        correlation_id: UUID | None = None,
    ) -> list[UUID]:
        """Stage one AgentSecret and its audit event in an existing transaction."""
        session.add(secret)
        session.flush()
        event = EVENT_REGISTRY.build_event(
            event_name=event_name,
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=organization_id,
            actor=actor,
            subject=SubjectIdentity(
                type=SubjectIdentityType.AGENT,
                id=secret.agent_id,
                organization_id=organization_id,
            ),
            correlation_id=correlation_id or uuid4(),
            payload={
                "organization_id": organization_id,
                "agent_id": secret.agent_id,
                "record_id": secret.id,
                "provider": SecretProvider(secret.provider).value,
                "label": secret.secret_name,
                "shared_reference_id": secret.shared_credential_id,
                "actor_display": actor_display or actor.type.value,
                "subject_display": agent_name,
            },
        )
        self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
        return list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))

    def save_secret_with_event(
        self,
        secret: AgentSecret,
        *,
        event_name: str,
        organization_id: UUID,
        agent_name: str,
        actor: ActorIdentity,
        actor_display: str | None = None,
        correlation_id: UUID | None = None,
    ) -> list[UUID]:
        """Save an AgentSecret row and stage its audit event in one transaction.

        `organization_id`/`agent_name` are required explicitly since AgentSecret
        carries neither. The payload never includes `secret.content`. `secret`
        is the same object the caller holds, so it picks up DB-assigned fields
        (e.g. `id`) in place; no need to return it.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            delivery_ids = self._stage_secret_with_event(
                session,
                secret,
                event_name=event_name,
                organization_id=organization_id,
                agent_name=agent_name,
                actor=actor,
                actor_display=actor_display,
                correlation_id=correlation_id,
            )
            session.commit()
            return delivery_ids

    def delete_secret_with_event(
        self,
        agent_id: UUID,
        provider: SecretProvider,
        *,
        organization_id: UUID,
        agent_name: str,
        actor: ActorIdentity,
        actor_display: str | None = None,
        correlation_id: UUID | None = None,
    ) -> list[UUID]:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            query = (
                select(AgentSecret)
                .where(col(AgentSecret.agent_id) == agent_id)
                .where(col(AgentSecret.provider) == provider)
            )
            secret = session.exec(query).first()
            if secret is None:
                return []
            record_id, label, shared_reference_id = secret.id, secret.secret_name, secret.shared_credential_id
            session.delete(secret)
            session.flush()
            event = EVENT_REGISTRY.build_event(
                event_name=AGENT_SECRET_REMOVED,
                schema_version=1,
                occurred_at=datetime.now(UTC),
                organization_id=organization_id,
                actor=actor,
                subject=SubjectIdentity(
                    type=SubjectIdentityType.AGENT,
                    id=agent_id,
                    organization_id=organization_id,
                ),
                correlation_id=correlation_id or uuid4(),
                payload={
                    "organization_id": organization_id,
                    "agent_id": agent_id,
                    "record_id": record_id,
                    "provider": SecretProvider(provider).value,
                    "label": label,
                    "shared_reference_id": shared_reference_id,
                    "actor_display": actor_display or actor.type.value,
                    "subject_display": agent_name,
                },
            )
            self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return delivery_ids

    def find_lifecycle_email_recipients(
        self, agent_id: UUID, organization_id: UUID
    ) -> list[AgentLifecycleEmailRecipient]:
        with Session(self.delegate.engine) as session:
            agent = session.exec(
                select(Agent).where(
                    col(Agent.id) == agent_id,
                    col(Agent.organization_id) == organization_id,
                    col(Agent.deleted_at).is_(None),
                )
            ).first()
            if agent is None:
                return []
            users: list[User] = []
            if agent.created_by_user_id is not None:
                creator = session.get(User, agent.created_by_user_id)
                if creator is not None:
                    users.append(creator)
            owner_users = session.exec(
                select(User)
                .join(OrganizationUser, col(OrganizationUser.user_id) == col(User.id))
                .join(AgentAccess, col(AgentAccess.membership_id) == col(OrganizationUser.id))
                .where(
                    col(AgentAccess.agent_id) == agent_id,
                    col(AgentAccess.organization_id) == organization_id,
                    col(AgentAccess.access_role_id) == AGENT_OWNER_ROLE_ID,
                )
            ).all()
            users.extend(owner_users)
        recipients: dict[str, AgentLifecycleEmailRecipient] = {}
        for user in users:
            recipients.setdefault(
                str(user.email).lower(),
                AgentLifecycleEmailRecipient(email=str(user.email), full_name=user.full_name),
            )
        return list(recipients.values())

    def find_notified_lifecycle_email_recipients(self, delivery_id: UUID) -> set[str]:
        with Session(self.delegate.engine) as session:
            return set(
                session.exec(
                    select(AgentLifecycleEmailReceipt.recipient_email).where(
                        col(AgentLifecycleEmailReceipt.delivery_id) == delivery_id
                    )
                ).all()
            )

    def record_lifecycle_email_recipient_notified(self, delivery_id: UUID, recipient_email: str) -> None:
        with Session(self.delegate.engine) as session:
            session.add(AgentLifecycleEmailReceipt(delivery_id=delivery_id, recipient_email=recipient_email))
            try:
                session.commit()
            except IntegrityError:
                # Concurrent/duplicate delivery of the same handler execution; the
                # receipt already exists, which is exactly the idempotency this records.
                session.rollback()

    def find_access_assignments(self, agent_id: UUID, organization_id: UUID) -> list[AgentAccess]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(AgentAccess).where(
                        col(AgentAccess.agent_id) == agent_id,
                        col(AgentAccess.organization_id) == organization_id,
                    )
                ).all()
            )

    def find_access_membership_ids(self, agent_id: UUID, organization_id: UUID) -> set[UUID]:
        return {access.membership_id for access in self.find_access_assignments(agent_id, organization_id)}

    def find_all_active_for_org(self, org_id: UUID) -> list[Agent]:
        with Session(self.delegate.engine) as session:
            query = (
                select(Agent)
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.deleted_at).is_(None))
                .order_by(col(Agent.created_at).asc())
            )
            return list(session.exec(query).all())

    def find_all_running(self) -> list[Agent]:
        """Live Agents currently eligible for an operator lifecycle cutover."""
        with Session(self.delegate.engine) as session:
            query = (
                select(Agent)
                .where(col(Agent.deleted_at).is_(None))
                .where(col(Agent.status) == AgentStatus.RUNNING)
                .order_by(col(Agent.organization_id), col(Agent.created_at))
            )
            return list(session.exec(query).all())

    def find_all_for_org(self, org_id: UUID) -> list[Agent]:
        """Return all agents for an org — both live and deleted."""
        with Session(self.delegate.engine) as session:
            query = select(Agent).where(col(Agent.organization_id) == org_id).order_by(col(Agent.created_at).asc())
            return list(session.exec(query).all())

    # --- Integration secrets ---

    def get_secret(self, agent_id: UUID, provider: SecretProvider) -> AgentSecret | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentSecret)
                .where(col(AgentSecret.agent_id) == agent_id)
                .where(col(AgentSecret.provider) == provider)
            )
            return session.exec(query).first()

    def get_secrets_for_agent(self, agent_id: UUID) -> list[AgentSecret]:
        with Session(self.delegate.engine) as session:
            query = select(AgentSecret).where(col(AgentSecret.agent_id) == agent_id)
            return list(session.exec(query).all())

    def get_secrets_for_agents(self, agent_ids: list[UUID]) -> dict[UUID, list[AgentSecret]]:
        if not agent_ids:
            return {}
        with Session(self.delegate.engine) as session:
            query = select(AgentSecret).where(col(AgentSecret.agent_id).in_(agent_ids))
            result: dict[UUID, list[AgentSecret]] = {}
            for secret in session.exec(query).all():
                result.setdefault(secret.agent_id, []).append(secret)
            return result

    # --- Skills ---

    def save_skills(self, skills: list[AgentSkill]) -> None:
        self.delegate.save_all(skills)

    def add_skill(self, agent_id: UUID, skill_id: UUID, *, pinned_version: int) -> None:
        with Session(self.delegate.engine) as session:
            existing = session.exec(
                select(AgentSkill)
                .where(col(AgentSkill.agent_id) == agent_id)
                .where(col(AgentSkill.skill_id) == skill_id)
            ).first()
            if existing is None:
                session.add(AgentSkill(agent_id=agent_id, skill_id=skill_id, pinned_version=pinned_version))
                session.commit()

    def re_pin_skill(self, agent_id: UUID, skill_id: UUID, pinned_version: int) -> None:
        """Point an existing assignment at a different skill version."""
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(AgentSkill)
                .where(col(AgentSkill.agent_id) == agent_id)
                .where(col(AgentSkill.skill_id) == skill_id)
            ).first()
            if row is not None:
                row.pinned_version = pinned_version
                session.add(row)
                session.commit()

    def remove_skill(self, agent_id: UUID, skill_id: UUID) -> None:
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(AgentSkill)
                .where(col(AgentSkill.agent_id) == agent_id)
                .where(col(AgentSkill.skill_id) == skill_id)
            ).first()
            if row is not None:
                session.delete(row)
                session.commit()

    def get_skills_for_agent(self, agent_id: UUID) -> list[AgentSkill]:
        with Session(self.delegate.engine) as session:
            query = select(AgentSkill).where(col(AgentSkill.agent_id) == agent_id)
            return list(session.exec(query).all())

    # --- Log snapshots ---

    def save_log_snapshot(self, snapshot: AgentLogSnapshot) -> AgentLogSnapshot:
        self.delegate.save(snapshot)
        return snapshot

    def get_latest_log_snapshot(self, agent_id: UUID) -> AgentLogSnapshot | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentLogSnapshot)
                .where(col(AgentLogSnapshot.agent_id) == agent_id)
                .order_by(col(AgentLogSnapshot.session_ended_at).desc())
                .limit(1)
            )
            return session.exec(query).first()

    def get_snapshot_by_id(self, agent_id: UUID, snapshot_id: UUID) -> AgentLogSnapshot | None:
        with Session(self.delegate.engine) as session:
            query = select(AgentLogSnapshot).where(
                col(AgentLogSnapshot.agent_id) == agent_id,
                col(AgentLogSnapshot.id) == snapshot_id,
            )
            return session.exec(query).first()

    def get_previous_snapshot(self, agent_id: UUID, before: datetime) -> AgentLogSnapshot | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentLogSnapshot)
                .where(
                    col(AgentLogSnapshot.agent_id) == agent_id,
                    col(AgentLogSnapshot.session_ended_at) < before,
                )
                .order_by(col(AgentLogSnapshot.session_ended_at).desc())
                .limit(1)
            )
            return session.exec(query).first()

    def delete_old_snapshots(self, agent_id: UUID, keep: int) -> None:
        with Session(self.delegate.engine) as session:
            keep_ids_query = (
                select(AgentLogSnapshot.id)
                .where(col(AgentLogSnapshot.agent_id) == agent_id)
                .order_by(col(AgentLogSnapshot.session_ended_at).desc())
                .limit(keep)
            )
            keep_ids = list(session.exec(keep_ids_query).all())
            if not keep_ids:
                return
            old_query = select(AgentLogSnapshot).where(
                col(AgentLogSnapshot.agent_id) == agent_id,
                col(AgentLogSnapshot.id).notin_(keep_ids),
            )
            old_snapshots = list(session.exec(old_query).all())
            for snap in old_snapshots:
                session.delete(snap)
            if old_snapshots:
                session.commit()

    def save(self, agent: Agent) -> Agent:
        self.delegate.save(agent)
        return agent

    def hard_delete(self, agent_id: UUID) -> None:
        self.delegate.delete_one(Agent, agent_id)
