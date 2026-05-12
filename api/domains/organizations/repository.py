from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import and_, func
from sqlmodel import Session, col, or_, select

from api.domains.organizations.models import (
    Organization,
    OrganizationFilter,
    OrganizationRead,
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
        return OrganizationRead(
            **organization.model_dump(), owner_email=owner_email, owner_name=owner_name
        )

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

    def _apply_organization_read_filters(
        self, query, organization_filter: OrganizationFilter
    ):
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

    def find_default(self) -> Organization | None:
        return self.delegate.find_one(Organization, is_default=True)

    def get(self, organization_id: UUID) -> Organization | None:
        return self.delegate.find_by_id(Organization, organization_id)

    def get_read(self, organization_id: UUID) -> OrganizationRead | None:
        with Session(self.delegate.engine) as session:
            query = self._build_organization_read_query().where(
                col(Organization.id) == organization_id
            )
            row = session.exec(query).first()
            if row is None:
                return None
            organization, owner_email, owner_name = row
            return self._to_organization_read(organization, owner_email, owner_name)

    def find_all_paginated_read(
        self,
        organization_filter: OrganizationFilter,
        pagination: Pagination | None = None,
        user_id: UUID | None = None,
    ) -> PaginatedItems[OrganizationRead]:
        with Session(self.delegate.engine) as session:
            query = self._build_organization_read_query()
            if user_id:
                query = query.where(col(OrganizationUser.user_id) == user_id)
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
                count_query = count_query.where(
                    col(OrganizationUser.user_id) == user_id
                )
            count_query = self._apply_organization_read_filters(
                count_query, organization_filter
            )
            total = session.scalar(count_query) or 0

            if pagination:
                query = query.offset((pagination.page - 1) * pagination.size).limit(
                    pagination.size
                )

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

    def save_with_session(
        self, organization: Organization, session: Session
    ) -> Organization:
        session.add(organization)
        session.flush()
        return organization

    def delete(self, organization_id: UUID) -> bool:
        return self.delegate.delete_one(Organization, organization_id)
