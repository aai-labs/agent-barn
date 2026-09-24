from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import Session, col, or_, select

from api.domains.events.repository import OutboxMessageRepository
from api.domains.organizations.exceptions import OrganizationCreationLimitReached
from api.domains.organizations.models import (
    Organization,
    OrganizationBudgetEmailReceipt,
    OrganizationFilter,
    OrganizationRead,
    PlatformOrganizationRead,
)
from api.domains.users.models import User
from api.domains.users.organization_users.models import (
    OrganizationRole,
    OrganizationUser,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import PaginatedItems, Pagination


def _deduped_recipients(rows) -> list[tuple[str, str | None]]:
    """One entry per address, compared case-insensitively while keeping the stored
    casing for display."""
    seen: dict[str, tuple[str, str | None]] = {}
    for email, full_name in rows:
        seen.setdefault(str(email).lower(), (str(email), full_name))
    return list(seen.values())


@inject
@singleton
@dataclass
class OrganizationRepository:
    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    @staticmethod
    def _to_organization_read(
        organization: Organization,
        owner_email: str | None,
        owner_name: str | None,
    ) -> OrganizationRead:
        return OrganizationRead(**organization.model_dump(), owner_email=owner_email, owner_name=owner_name)

    def _build_organization_read_query(self):
        user_email = col(User.email).label("owner_email")
        user_name = col(User.full_name).label("owner_name")

        return (
            select(
                Organization,
                user_email,
                user_name,
            )
            .outerjoin(
                OrganizationUser,
                and_(
                    col(OrganizationUser.organization_id) == Organization.id,
                    col(OrganizationUser.role) == OrganizationRole.OWNER,
                ),
            )
            .outerjoin(User, col(User.id) == col(OrganizationUser.user_id))
        )

    @staticmethod
    def _build_platform_organization_read_query():
        owner = aliased(User)
        creator = aliased(User)
        return (
            select(
                col(Organization.id).label("id"),
                col(Organization.created_at).label("created_at"),
                col(Organization.updated_at).label("updated_at"),
                col(Organization.name).label("name"),
            )
            .add_columns(
                col(Organization.description).label("description"),
                col(owner.id).label("owner_user_id"),
                col(owner.email).label("owner_email"),
                col(owner.full_name).label("owner_name"),
                col(creator.id).label("creator_user_id"),
                col(creator.email).label("creator_email"),
                col(creator.full_name).label("creator_name"),
                col(Organization.llm_budget_usd).label("llm_budget_usd"),
                col(Organization.llm_budget_duration).label("llm_budget_duration"),
            )
            .select_from(Organization)
            .outerjoin(
                OrganizationUser,
                and_(
                    col(OrganizationUser.organization_id) == Organization.id,
                    col(OrganizationUser.role) == OrganizationRole.OWNER,
                ),
            )
            .outerjoin(owner, col(owner.id) == col(OrganizationUser.user_id))
            .outerjoin(creator, col(creator.id) == col(Organization.created_by_user_id)),
            owner,
        )

    @staticmethod
    def _to_platform_organization_read(row) -> PlatformOrganizationRead:
        return PlatformOrganizationRead(**row._mapping)

    @staticmethod
    def _member_of_organization(user_id: UUID):
        # Scope "my orgs" by *any* membership, correlated to the outer Organization.
        # Deliberately separate from the owner-display join above (which is OWNER-only,
        # just for the email/name columns) so non-owner members aren't filtered out.
        member = aliased(OrganizationUser)
        return (
            select(member.id)
            .where(
                col(member.organization_id) == Organization.id,
                col(member.user_id) == user_id,
            )
            .exists()
        )

    def _apply_organization_read_filters(self, query, organization_filter: OrganizationFilter):
        if organization_filter.search:
            search = f"%{organization_filter.search}%"
            query = query.where(
                or_(
                    col(Organization.name).ilike(search),
                    col(Organization.description).ilike(search),
                    col(User.email).ilike(search),
                    col(User.full_name).ilike(search),
                )
            )

        return query

    def find_budget_email_recipients(self, organization_id: UUID) -> list[tuple[str, str | None]]:
        """Owners and Admins, i.e. the same audience `cost.read` gives the figures to.
        Plain members are deliberately excluded."""
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(User.email, User.full_name)
                .join(OrganizationUser, col(OrganizationUser.user_id) == col(User.id))
                .where(
                    col(OrganizationUser.organization_id) == organization_id,
                    col(OrganizationUser.role).in_([OrganizationRole.OWNER, OrganizationRole.ADMIN]),
                )
            ).all()
        return _deduped_recipients(rows)

    def find_platform_admin_recipients(self) -> list[tuple[str, str | None]]:
        """Platform Administrators, for the one budget event that is our problem too:
        an Organization cut off from model calls is a support ticket inbound."""
        with Session(self.delegate.engine) as session:
            rows = session.exec(select(User.email, User.full_name).where(col(User.is_platform_admin).is_(True))).all()
        return _deduped_recipients(rows)

    def find_notified_budget_recipients(self, delivery_id: UUID) -> set[str]:
        with Session(self.delegate.engine) as session:
            return set(
                session.exec(
                    select(OrganizationBudgetEmailReceipt.recipient_email).where(
                        col(OrganizationBudgetEmailReceipt.delivery_id) == delivery_id
                    )
                ).all()
            )

    def record_budget_recipient_notified(self, delivery_id: UUID, recipient_email: str) -> None:
        with Session(self.delegate.engine) as session:
            session.add(OrganizationBudgetEmailReceipt(delivery_id=delivery_id, recipient_email=recipient_email))
            try:
                session.commit()
            except IntegrityError:
                # The receipt already exists, which is exactly the idempotency it records.
                session.rollback()

    def list_capped_organizations(self) -> list[Organization]:
        """Organizations with a spend limit set. Uncapped ones have nothing to
        threshold against, so they are never read from the proxy at all."""
        with Session(self.delegate.engine) as session:
            return list(session.exec(select(Organization).where(col(Organization.llm_budget_usd).is_not(None))).all())

    def list_budget_policies(self) -> list[tuple[UUID, float | None, str | None]]:
        """System-only inventory of LLM spend policy; never exposed through a route."""
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(Organization.id, Organization.llm_budget_usd, Organization.llm_budget_duration)
            ).all()
            return [(row[0], row[1], row[2]) for row in rows]

    def get(self, organization_id: UUID) -> Organization | None:
        return self.delegate.find_by_id(Organization, organization_id)

    def get_read(self, organization_id: UUID) -> OrganizationRead | None:
        with Session(self.delegate.engine) as session:
            query = self._build_organization_read_query().where(col(Organization.id) == organization_id)
            row = session.exec(query).first()
            if row is None:
                return None
            organization, owner_email, owner_name = row
            return self._to_organization_read(organization, owner_email, owner_name)

    def get_platform_read(self, organization_id: UUID) -> PlatformOrganizationRead | None:
        with Session(self.delegate.engine) as session:
            query, _ = self._build_platform_organization_read_query()
            query = query.where(col(Organization.id) == organization_id)
            row = session.exec(query).first()
            if row is None:
                return None
            return self._to_platform_organization_read(row)

    @staticmethod
    def _apply_platform_organization_filters(query, organization_filter: OrganizationFilter, owner):
        if organization_filter.search:
            search = f"%{organization_filter.search}%"
            query = query.where(
                or_(
                    col(Organization.name).ilike(search),
                    col(Organization.description).ilike(search),
                    col(owner.email).ilike(search),
                    col(owner.full_name).ilike(search),
                )
            )
        return query

    @staticmethod
    def _build_platform_organization_count_query():
        owner = aliased(User)
        return (
            select(func.count(func.distinct(Organization.id)))
            .select_from(Organization)
            .outerjoin(
                OrganizationUser,
                and_(
                    col(OrganizationUser.organization_id) == Organization.id,
                    col(OrganizationUser.role) == OrganizationRole.OWNER,
                ),
            )
            .outerjoin(owner, col(owner.id) == col(OrganizationUser.user_id)),
            owner,
        )

    def find_all_paginated_platform_read(
        self,
        organization_filter: OrganizationFilter,
        pagination: Pagination | None = None,
    ) -> PaginatedItems[PlatformOrganizationRead]:
        with Session(self.delegate.engine) as session:
            query, owner = self._build_platform_organization_read_query()
            query = self._apply_platform_organization_filters(query, organization_filter, owner)
            query = query.order_by(col(Organization.updated_at).asc())

            count_query, count_owner = self._build_platform_organization_count_query()
            count_query = self._apply_platform_organization_filters(count_query, organization_filter, count_owner)
            total = session.scalar(count_query) or 0

            if pagination:
                query = query.offset((pagination.page - 1) * pagination.size).limit(pagination.size)

            rows = session.exec(query).all()
            items = [self._to_platform_organization_read(row) for row in rows]

            return PaginatedItems(
                page=pagination.page if pagination else 1,
                page_size=pagination.size if pagination else len(items),
                total=total,
                items=items,
            )

    def find_all_paginated_read(
        self,
        organization_filter: OrganizationFilter,
        pagination: Pagination | None = None,
        user_id: UUID | None = None,
    ) -> PaginatedItems[OrganizationRead]:
        with Session(self.delegate.engine) as session:
            query = self._build_organization_read_query()
            if user_id:
                query = query.where(self._member_of_organization(user_id))
            query = self._apply_organization_read_filters(query, organization_filter)
            query = query.order_by(col(Organization.updated_at).asc())

            count_query = (
                select(func.count(func.distinct(Organization.id)))
                .select_from(Organization)
                .outerjoin(
                    OrganizationUser,
                    and_(
                        col(OrganizationUser.organization_id) == Organization.id,
                        col(OrganizationUser.role) == OrganizationRole.OWNER,
                    ),
                )
                .outerjoin(User, col(User.id) == col(OrganizationUser.user_id))
            )
            if user_id:
                count_query = count_query.where(self._member_of_organization(user_id))
            count_query = self._apply_organization_read_filters(count_query, organization_filter)
            total = session.scalar(count_query) or 0

            if pagination:
                query = query.offset((pagination.page - 1) * pagination.size).limit(pagination.size)

            rows = session.exec(query).all()
            items = [
                self._to_organization_read(organization, owner_email, owner_name)
                for organization, owner_email, owner_name in rows
            ]

            return PaginatedItems(
                page=pagination.page if pagination else 1,
                page_size=pagination.size if pagination else len(items),
                total=total,
                items=items,
            )

    def save(self, organization: Organization) -> Organization:
        self.delegate.save(organization)
        return organization

    def save_with_session(self, organization: Organization, session: Session) -> Organization:
        session.add(organization)
        session.flush()
        return organization

    def create_for_user(
        self,
        organization: Organization,
        creator_id: UUID,
        creation_limit: int,
    ) -> Organization:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            # Serialize creation attempts for one user. Without this lock, two
            # concurrent requests could both observe one remaining quota slot.
            creator = session.exec(select(User).where(col(User.id) == creator_id).with_for_update()).one()
            created_count = session.scalar(
                select(func.count()).select_from(Organization).where(col(Organization.created_by_user_id) == creator.id)
            )
            if (created_count or 0) >= creation_limit:
                raise OrganizationCreationLimitReached(creation_limit)

            session.add(organization)
            session.flush()
            session.add(
                OrganizationUser(
                    user_id=creator.id,
                    organization_id=organization.id,
                    role=OrganizationRole.OWNER,
                )
            )
            session.commit()
            return organization

    def delete(self, organization_id: UUID) -> bool:
        return self.delegate.delete_one(Organization, organization_id)
