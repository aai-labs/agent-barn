from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import and_, func
from sqlalchemy.orm import aliased
from sqlmodel import Session, col, or_, select

from api.domains.organizations.exceptions import OrganizationCreationLimitReached
from api.domains.organizations.models import (
    Organization,
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


@inject
@singleton
@dataclass
class OrganizationRepository:
    delegate: PostgresRepositoryDelegate

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
        owner = aliased(User)
        creator = aliased(User)
        with Session(self.delegate.engine) as session:
            query = (
                select(Organization, owner, creator)
                .outerjoin(
                    OrganizationUser,
                    and_(
                        col(OrganizationUser.organization_id) == Organization.id,
                        col(OrganizationUser.role) == OrganizationRole.OWNER,
                    ),
                )
                .outerjoin(owner, col(owner.id) == col(OrganizationUser.user_id))
                .outerjoin(creator, col(creator.id) == Organization.created_by_user_id)
                .where(col(Organization.id) == organization_id)
            )
            row = session.exec(query).first()
            if row is None:
                return None
            organization, owner_user, creator_user = row
            return PlatformOrganizationRead(
                **organization.model_dump(),
                owner_user_id=owner_user.id if owner_user else None,
                owner_email=owner_user.email if owner_user else None,
                owner_name=owner_user.full_name if owner_user else None,
                creator_user_id=creator_user.id if creator_user else None,
                creator_email=creator_user.email if creator_user else None,
                creator_name=creator_user.full_name if creator_user else None,
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
