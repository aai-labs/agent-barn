from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.events.catalog import (
    EVENT_REGISTRY,
    PLATFORM_USER_PRIVILEGE_GRANTED,
    PLATFORM_USER_PRIVILEGE_REVOKED,
)
from api.domains.events.models import (
    ActorIdentity,
    ActorIdentityType,
    EventDelivery,
    EventScope,
    SubjectIdentity,
    SubjectIdentityType,
)
from api.domains.events.repository import OutboxMessageRepository
from api.domains.users.exceptions import (
    EmailTakenHTTPException,
    LastPlatformAdministrator,
    PlatformPrivilegeAlreadySet,
)
from api.domains.users.models import User, UserFilter
from api.domains.users.organization_users.models import (
    OrganizationRole,
    OrganizationUser,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import PaginatedItems, Pagination


@dataclass(frozen=True)
class PlatformPrivilegeChangeResult:
    user: User
    delivery_ids: list[UUID]


@inject
@singleton
@dataclass
class UserRepository:
    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    def get(self, user_id: UUID) -> User | None:
        query = select(User).where(col(User.id) == user_id)

        rows = self.delegate.find_all_by_query(model=User, query=query)
        return rows[0] if rows else None

    def get_by_id_and_organization_id(self, user_id: UUID, organization_id: UUID) -> User | None:
        query = (
            select(User)
            .join(OrganizationUser, col(OrganizationUser.user_id) == col(User.id))
            .where(
                col(User.id) == user_id,
                col(OrganizationUser.organization_id) == organization_id,
            )
        )
        return self.delegate.find_one_by_query(model=User, query=query)

    def get_organization_owner(self, organization_id: UUID) -> User | None:
        query = (
            select(User)
            .join(OrganizationUser, col(OrganizationUser.user_id) == col(User.id))
            .where(
                col(OrganizationUser.organization_id) == organization_id,
                col(OrganizationUser.role) == OrganizationRole.OWNER,
            )
        )
        return self.delegate.find_one_by_query(model=User, query=query)

    def get_by_email(self, email: str) -> User | None:
        query = select(User).where(col(User.email) == email)
        rows = self.delegate.find_all_by_query(model=User, query=query)
        return rows[0] if rows else None

    def count_platform_admins(self) -> int:
        # A platform may have any number of administrators — change_platform_privilege
        # only forbids dropping to zero — so callers ask how many there are rather
        # than for "the" administrator.
        query = select(User).where(col(User.is_platform_admin).is_(True))
        return self.delegate.count_by_query(query)

    def find_one(self, **kwargs) -> User | None:
        return self.delegate.find_one(User, **kwargs)

    def _get_query(
        self,
        query_filters: UserFilter,
        organization_id: UUID | None = None,
    ):
        query = select(User)

        if organization_id:
            query = query.join(OrganizationUser, col(OrganizationUser.user_id) == col(User.id))
            query = query.where(
                col(OrganizationUser.organization_id) == organization_id,
                col(User.is_platform_admin).is_(False),
            )

            if query_filters.organization_roles:
                query = query.where(col(OrganizationUser.role).in_(query_filters.organization_roles))

        if query_filters.search:
            search_pattern = f"%{query_filters.search}%"
            query = query.where(
                or_(
                    col(User.email).ilike(search_pattern),
                    col(User.full_name).ilike(search_pattern),
                )
            )

        if query_filters.user_ids:
            query = query.where(col(User.id).in_(query_filters.user_ids))

        return query

    def find_all(
        self,
        query_filters: UserFilter,
        organization_id: UUID | None = None,
    ) -> list[User]:
        query = self._get_query(query_filters, organization_id=organization_id)
        return self.delegate.find_all_by_query(model=User, query=query, order_by=[("updated_at", "asc")])

    def find_all_paginated(
        self,
        query_filters: UserFilter,
        pagination: Pagination,
        organization_id: UUID | None = None,
    ) -> PaginatedItems[User]:
        query = self._get_query(query_filters, organization_id)
        return self.delegate.find_all_paginated_by_query(
            model=User,
            query=query,
            pagination=pagination,
            order_by=[("updated_at", "asc")],
        )

    def find_all_by_ids(self, ids: list[UUID]) -> list[User]:
        query = select(User).where(col(User.id).in_(ids))
        return self.delegate.find_all_by_query(model=User, query=query)

    def count(self) -> int:
        return self.delegate.count(User)

    def save(self, user: User) -> User:
        email = user.email
        try:
            self.delegate.save(user)
            return user
        except IntegrityError as e:
            if "email" in str(e).lower() and "unique" in str(e).lower():
                raise EmailTakenHTTPException(email)
            raise

    def change_platform_privilege(
        self,
        *,
        actor_id: UUID,
        subject_id: UUID,
        is_platform_admin: bool,
        reason: str,
    ) -> PlatformPrivilegeChangeResult | None:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            # Lock the complete administrator set as well as the target. Concurrent
            # revocations therefore cannot each believe another administrator remains.
            locked_users = list(
                session.exec(
                    select(User)
                    .where(
                        or_(
                            col(User.is_platform_admin).is_(True),
                            col(User.id) == subject_id,
                        )
                    )
                    .order_by(col(User.id))
                    .with_for_update()
                )
            )
            subject = next((user for user in locked_users if user.id == subject_id), None)
            actor = next((user for user in locked_users if user.id == actor_id), None)
            if subject is None:
                return None
            if actor is None:
                return None
            if subject.is_platform_admin == is_platform_admin:
                raise PlatformPrivilegeAlreadySet()
            if not is_platform_admin:
                platform_admin_count = sum(user.is_platform_admin for user in locked_users)
                if platform_admin_count <= 1:
                    raise LastPlatformAdministrator()

            subject.is_platform_admin = is_platform_admin
            session.add(subject)
            session.flush()

            event_name = PLATFORM_USER_PRIVILEGE_GRANTED if is_platform_admin else PLATFORM_USER_PRIVILEGE_REVOKED
            event = EVENT_REGISTRY.build_event(
                event_name=event_name,
                schema_version=1,
                occurred_at=datetime.now(UTC),
                event_scope=EventScope.PLATFORM,
                organization_id=None,
                actor=ActorIdentity(type=ActorIdentityType.USER, id=actor_id),
                subject=SubjectIdentity(type=SubjectIdentityType.USER, id=subject_id),
                correlation_id=uuid4(),
                payload={
                    "actor_user_id": actor_id,
                    "actor_display": actor.email,
                    "subject_user_id": subject_id,
                    "subject_display": subject.email,
                    "reason": reason,
                },
            )
            self.outbox_repository.stage(
                session=session,
                event=event,
                registry=EVENT_REGISTRY,
            )
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return PlatformPrivilegeChangeResult(
                user=subject,
                delivery_ids=delivery_ids,
            )

    def get_by_email_with_session(self, email: str, session: Session) -> User | None:
        return session.exec(select(User).where(col(User.email) == email)).first()

    def save_with_session(self, user: User, session: Session) -> User:
        email = user.email
        try:
            session.add(user)
            session.flush()
            return user
        except IntegrityError as e:
            if "email" in str(e).lower() and "unique" in str(e).lower():
                raise EmailTakenHTTPException(email)
            raise

    def save_all(self, users: list[User]) -> None:
        self.delegate.save_all(users)

    def delete_all(self) -> bool:
        return self.delegate.delete_all(User)

    def delete(self, user_id: UUID) -> bool:
        return self.delegate.delete_one(User, user_id)

    def close(self) -> None:
        self.delegate.close()
