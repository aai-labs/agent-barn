from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlalchemy import exists, func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.agents.exceptions import BotTokenConflictHTTPException
from api.domains.agents.models import (
    Agent,
    AgentAccess,
    AgentFilter,
    AgentLifecycleEmailReceipt,
    AgentLogSnapshot,
    AgentSecret,
    AgentSkill,
    AgentSlackConfig,
    AgentTeamsConfig,
    AgentTelegramConfig,
    SecretProvider,
)
from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import (
    AGENT_ACCESS_GRANTED,
    AGENT_ACCESS_REVOKED,
    AGENT_CREATED,
    AGENT_GENERAL_ACCESS_CHANGED,
    EVENT_REGISTRY,
)
from api.domains.events.repository import OutboxMessageRepository
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
        correlation_id: UUID | None = None,
    ) -> bool:
        """Replace General Access and explicit assignments atomically."""
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
                return False

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
                    return False

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
                    return False

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
            audit_correlation_id = correlation_id or uuid4()

            if previous_general_access_role_id != general_access_role_id:
                self.outbox_repository.stage(
                    session=session,
                    registry=EVENT_REGISTRY,
                    event=EVENT_REGISTRY.build_event(
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
                        },
                    ),
                )

            for membership_id, access in existing_by_membership.items():
                if membership_id not in desired_membership_ids:
                    self.outbox_repository.stage(
                        session=session,
                        registry=EVENT_REGISTRY,
                        event=EVENT_REGISTRY.build_event(
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
                            },
                        ),
                    )
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
                    self.outbox_repository.stage(
                        session=session,
                        registry=EVENT_REGISTRY,
                        event=EVENT_REGISTRY.build_event(
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
                            },
                        ),
                    )
                else:
                    access.access_role_id = access_role_id
                    session.add(access)

            session.commit()
            return True

    def create_with_creator_access(
        self,
        agent: Agent,
        membership_id: UUID | None,
        *,
        actor: ActorIdentity,
        correlation_id: UUID | None = None,
    ) -> AgentLifecycleEventResult:
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
                    "platform": agent.platform,
                    "runtime": agent.agent_type,
                    "created_by_user_id": agent.created_by_user_id,
                },
            )
            self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            session.refresh(agent)
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
            persisted.status = agent.status
            persisted.last_error = agent.last_error
            persisted.ingest_key_encrypted = agent.ingest_key_encrypted
            session.add(persisted)
            session.flush()
            payload: dict[str, Any] = {
                "organization_id": persisted.organization_id,
                "agent_id": persisted.id,
                "agent_name": persisted.name,
                "platform": persisted.platform,
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

    def find_all_for_org(self, org_id: UUID) -> list[Agent]:
        """Return all agents for an org — both live and deleted."""
        with Session(self.delegate.engine) as session:
            query = select(Agent).where(col(Agent.organization_id) == org_id).order_by(col(Agent.created_at).asc())
            return list(session.exec(query).all())

    # --- Slack config ---

    def get_slack_config(self, agent_id: UUID) -> AgentSlackConfig | None:
        with Session(self.delegate.engine) as session:
            query = select(AgentSlackConfig).where(col(AgentSlackConfig.agent_id) == agent_id)
            return session.exec(query).first()

    def save_slack_config(self, config: AgentSlackConfig) -> AgentSlackConfig:
        try:
            self.delegate.save(config)
        except IntegrityError as e:
            if "ix_agent_slack_config_bot_token_hash" in str(e).lower():
                raise BotTokenConflictHTTPException("another agent")
            raise
        return config

    def find_active_agent_by_bot_token_hash(
        self, bot_token_hash: str, exclude_agent_id: UUID | None = None
    ) -> Agent | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(Agent)
                .join(AgentSlackConfig, col(AgentSlackConfig.agent_id) == col(Agent.id))
                .where(col(AgentSlackConfig.bot_token_hash) == bot_token_hash)
                .where(col(Agent.deleted_at).is_(None))
            )
            if exclude_agent_id is not None:
                query = query.where(col(Agent.id) != exclude_agent_id)
            return session.exec(query).first()

    def get_slack_configs_for_agents(self, agent_ids: list[UUID]) -> dict[UUID, AgentSlackConfig]:
        if not agent_ids:
            return {}
        with Session(self.delegate.engine) as session:
            query = select(AgentSlackConfig).where(col(AgentSlackConfig.agent_id).in_(agent_ids))
            return {c.agent_id: c for c in session.exec(query).all()}

    # --- Teams config ---

    def get_teams_config(self, agent_id: UUID) -> AgentTeamsConfig | None:
        with Session(self.delegate.engine) as session:
            query = select(AgentTeamsConfig).where(col(AgentTeamsConfig.agent_id) == agent_id)
            return session.exec(query).first()

    def save_teams_config(self, config: AgentTeamsConfig) -> AgentTeamsConfig:
        self.delegate.save(config)
        return config

    def get_teams_configs_for_agents(self, agent_ids: list[UUID]) -> dict[UUID, AgentTeamsConfig]:
        if not agent_ids:
            return {}
        with Session(self.delegate.engine) as session:
            query = select(AgentTeamsConfig).where(col(AgentTeamsConfig.agent_id).in_(agent_ids))
            return {c.agent_id: c for c in session.exec(query).all()}

    # --- Telegram config ---

    def get_telegram_config(self, agent_id: UUID) -> AgentTelegramConfig | None:
        with Session(self.delegate.engine) as session:
            query = select(AgentTelegramConfig).where(col(AgentTelegramConfig.agent_id) == agent_id)
            return session.exec(query).first()

    def save_telegram_config(self, config: AgentTelegramConfig) -> AgentTelegramConfig:
        self.delegate.save(config)
        return config

    def get_telegram_configs_for_agents(self, agent_ids: list[UUID]) -> dict[UUID, AgentTelegramConfig]:
        if not agent_ids:
            return {}
        with Session(self.delegate.engine) as session:
            query = select(AgentTelegramConfig).where(col(AgentTelegramConfig.agent_id).in_(agent_ids))
            return {c.agent_id: c for c in session.exec(query).all()}

    # --- Integration secrets ---

    def save_secret(self, secret: AgentSecret) -> AgentSecret:
        self.delegate.save(secret)
        return secret

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

    def delete_secret(self, agent_id: UUID, provider: SecretProvider) -> None:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentSecret)
                .where(col(AgentSecret.agent_id) == agent_id)
                .where(col(AgentSecret.provider) == provider)
            )
            secret = session.exec(query).first()
            if secret is not None:
                session.delete(secret)
                session.commit()

    # --- Skills ---

    def save_skills(self, skills: list[AgentSkill]) -> None:
        self.delegate.save_all(skills)

    def add_skill(self, agent_id: UUID, skill_id: UUID) -> None:
        with Session(self.delegate.engine) as session:
            existing = session.exec(
                select(AgentSkill)
                .where(col(AgentSkill.agent_id) == agent_id)
                .where(col(AgentSkill.skill_id) == skill_id)
            ).first()
            if existing is None:
                session.add(AgentSkill(agent_id=agent_id, skill_id=skill_id))
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
