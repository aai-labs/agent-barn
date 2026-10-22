from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import Session, col, or_, select

from api.domains.agent_sizes.models import OrganizationAgentSize
from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import (
    EVENT_REGISTRY,
    ORGANIZATION_AGENT_LIMIT_CHANGED,
    ORGANIZATION_CREATED,
    ORGANIZATION_DELETED,
    ORGANIZATION_LLM_BUDGET_CHANGED,
    ORGANIZATION_TRIAL_ENDED,
    ORGANIZATION_TRIAL_EXPIRED,
)
from api.domains.events.repository import OutboxMessageRepository
from api.domains.organizations.exceptions import (
    LlmBudgetAboveCeiling,
    OrganizationCreationLimitReached,
    OrganizationNotOnCredit,
)
from api.domains.organizations.models import (
    CreditGrantCreate,
    CreditGrantKind,
    Organization,
    OrganizationBudgetEmailReceipt,
    OrganizationCreditGrant,
    OrganizationFilter,
    OrganizationRead,
    PlatformCreditGrantRead,
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


# The audit reason a ceiling moved because the Organization's credit did.
_CREDIT_REASONS = {
    CreditGrantKind.TRIAL: "Trial credit granted.",
    CreditGrantKind.PURCHASE: "Credit purchased.",
    CreditGrantKind.REFUND: "Purchase refunded.",
    CreditGrantKind.CHARGEBACK: "Payment disputed.",
    CreditGrantKind.ADJUSTMENT: "Credit adjusted.",
}


@dataclass(frozen=True)
class CreditGrantResult:
    organization: Organization
    delivery_ids: list[UUID]
    # False when the grant's external reference had already been granted.
    applied: bool


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
                col(Organization.llm_own_budget_usd).label("llm_own_budget_usd"),
                col(Organization.is_trial).label("is_trial"),
                # ARRAY(subquery) is empty rather than NULL when nothing is allowed.
                func.array(
                    select(OrganizationAgentSize.agent_size_id)
                    .where(col(OrganizationAgentSize.organization_id) == Organization.id)
                    .order_by(col(OrganizationAgentSize.agent_size_id))
                    .scalar_subquery()
                ).label("agent_size_ids"),
                col(Organization.trial_expired_at).label("trial_expired_at"),
                col(Organization.agent_limit).label("agent_limit"),
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
        """Organizations with a spend limit set — since AF-337 every Organization has
        one, so this is all of them; the filter only guards rows mid-migration."""
        with Session(self.delegate.engine) as session:
            return list(session.exec(select(Organization).where(col(Organization.llm_budget_usd).is_not(None))).all())

    def list_budget_policies(self) -> list[tuple[UUID, float, str]]:
        """System-only inventory of the limit each team should carry: the
        Organization's own where one is in force, else the ceiling. Never exposed
        through a route."""
        with Session(self.delegate.engine) as session:
            organizations = session.exec(select(Organization)).all()
            return [
                (organization.id, float(organization.effective_llm_budget_usd), organization.llm_budget_duration)
                for organization in organizations
            ]

    def set_llm_budget_renews_at(self, organization_id: UUID, renews_at: datetime) -> None:
        """When the Organization's window renews, as the proxy reported it. Written on
        its own so it never races a concurrent limit change."""
        with Session(self.delegate.engine) as session:
            organization = session.get(Organization, organization_id)
            if organization is None:
                return
            organization.llm_budget_renews_at = renews_at
            session.add(organization)
            session.commit()

    def set_llm_ceiling_with_event(
        self,
        organization_id: UUID,
        *,
        ceiling_usd: float,
        window: str | None,
        actor: ActorIdentity,
        actor_display: str,
        reason_if_lowered: str,
    ) -> tuple[Organization, list[UUID]] | None:
        """Set the platform ceiling, pulling the Organization's own limit down to it if
        it is higher, and stage the change Event atomically.

        The own limit is compared under the row lock, not as the caller last read it:
        an own limit saved concurrently is still clamped instead of escaping above
        the new ceiling. A `window` of None keeps the one in force. None when the
        Organization does not exist.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            organization = self._locked(session, organization_id)
            if organization is None:
                return None
            window = window or organization.llm_budget_duration
            on_credit = window == organization.llm_budget_duration and organization.runs_on_credit
            if on_credit:
                # The ledger must keep adding up to the ceiling, so the difference is
                # recorded rather than the ceiling simply overwritten.
                difference = Decimal(str(ceiling_usd)) - self._credit_total(session, organization_id)
                if difference:
                    self._add_credit_grant(
                        session, organization_id, CreditGrantKind.ADJUSTMENT, difference, actor_display=actor_display
                    )
                if difference > 0:
                    # Credit to spend again makes an expired trial active again. Still spent
                    # after it, the next budget check alerts anew and expires it again.
                    organization.trial_expired_at = None
            own = None if on_credit else organization.llm_own_budget_usd
            lowered = own is not None and own > ceiling_usd
            return self._write_llm_budgets(
                session,
                organization,
                ceiling_usd=ceiling_usd,
                window=window,
                own_limit_usd=ceiling_usd if lowered else own,
                actor=actor,
                actor_display=actor_display,
                reason=reason_if_lowered if lowered else None,
            )

    def set_own_llm_budget_with_event(
        self,
        organization_id: UUID,
        *,
        own_limit_usd: float | None,
        actor: ActorIdentity,
        actor_display: str,
    ) -> tuple[Organization, list[UUID]] | None:
        """Set the Organization's own limit and stage the change Event atomically.

        Checked against the ceiling under the row lock and written without touching
        it, so a ceiling lowered by a concurrent request can neither be exceeded nor
        written back. Raises LlmBudgetAboveCeiling; None when the Organization does
        not exist.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            organization = self._locked(session, organization_id)
            if organization is None:
                return None
            if own_limit_usd is not None and own_limit_usd > organization.llm_budget_usd:
                raise LlmBudgetAboveCeiling(organization.llm_budget_usd)
            return self._write_llm_budgets(
                session,
                organization,
                ceiling_usd=organization.llm_budget_usd,
                window=organization.llm_budget_duration,
                own_limit_usd=own_limit_usd,
                actor=actor,
                actor_display=actor_display,
                reason=None,
            )

    def grant_credit_with_event(
        self,
        organization_id: UUID,
        grant: CreditGrantCreate,
        *,
        actor: ActorIdentity,
        actor_display: str,
    ) -> CreditGrantResult | None:
        """Record a grant and set the ceiling to the sum of the ledger, with the audit
        Event in the same commit. A grant whose external reference was already granted
        changes nothing. None when the Organization does not exist.

        The ceiling never goes below zero; the balance can, since spend is counted
        against the ceiling, and the next grant pays that off first.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            organization = self._locked(session, organization_id)
            if organization is None:
                return None
            if not organization.runs_on_credit:
                raise OrganizationNotOnCredit(organization_id)
            if grant.external_ref is not None and self._already_granted(session, grant.external_ref):
                return CreditGrantResult(organization, [], applied=False)
            try:
                self._add_credit_grant(
                    session,
                    organization_id,
                    grant.kind,
                    grant.credit_usd,
                    actor_display=actor_display,
                    amount_paid_usd=grant.amount_paid_usd,
                    external_ref=grant.external_ref,
                    note=grant.note,
                )
            except IntegrityError:
                # The check above runs under this Organization's lock only; the unique
                # constraint settles a reference granted at the same moment elsewhere.
                session.rollback()
                return CreditGrantResult(organization, [], applied=False)
            stored, delivery_ids = self._write_llm_budgets(
                session,
                organization,
                ceiling_usd=max(0.0, float(self._credit_total(session, organization_id))),
                window=organization.llm_budget_duration,
                own_limit_usd=None,
                actor=actor,
                actor_display=actor_display,
                reason=_CREDIT_REASONS[grant.kind],
            )
            return CreditGrantResult(stored, delivery_ids, applied=True)

    def record_opening_credit(self, organization_id: UUID, kind: CreditGrantKind, credit_usd: Decimal) -> None:
        """Open the ledger of an Organization whose ceiling is already set to `credit_usd`."""
        with Session(self.delegate.engine) as session:
            self.record_opening_credit_with_session(session, organization_id, kind, credit_usd)
            session.commit()

    def record_opening_credit_with_session(
        self, session: Session, organization_id: UUID, kind: CreditGrantKind, credit_usd: Decimal
    ) -> None:
        self._add_credit_grant(session, organization_id, kind, credit_usd, actor_display="Opening balance")

    def list_credit_grants(self, organization_id: UUID) -> list[OrganizationCreditGrant]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(OrganizationCreditGrant)
                    .where(col(OrganizationCreditGrant.organization_id) == organization_id)
                    .order_by(col(OrganizationCreditGrant.created_at), col(OrganizationCreditGrant.id))
                ).all()
            )

    def get_credit_grant_by_ref(self, external_ref: str) -> OrganizationCreditGrant | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(OrganizationCreditGrant).where(col(OrganizationCreditGrant.external_ref) == external_ref)
            ).first()

    def list_all_credit_grants(
        self,
        pagination: Pagination,
        *,
        kind: CreditGrantKind | None = None,
        organization_id: UUID | None = None,
    ) -> PaginatedItems[PlatformCreditGrantRead]:
        """Every Organization's Credit Grants, newest first."""
        conditions = []
        if kind is not None:
            conditions.append(col(OrganizationCreditGrant.kind) == kind)
        if organization_id is not None:
            conditions.append(col(OrganizationCreditGrant.organization_id) == organization_id)
        with Session(self.delegate.engine) as session:
            total = session.scalar(select(func.count()).select_from(OrganizationCreditGrant).where(*conditions)) or 0
            rows = session.exec(
                select(OrganizationCreditGrant, Organization.name)
                .join(Organization, col(Organization.id) == col(OrganizationCreditGrant.organization_id))
                .where(*conditions)
                .order_by(col(OrganizationCreditGrant.created_at).desc(), col(OrganizationCreditGrant.id).desc())
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            ).all()
            return PaginatedItems(
                page=pagination.page,
                page_size=pagination.size,
                total=total,
                items=[
                    PlatformCreditGrantRead.model_validate({**grant.model_dump(), "organization_name": name})
                    for grant, name in rows
                ],
            )

    @staticmethod
    def _add_credit_grant(
        session: Session,
        organization_id: UUID,
        kind: CreditGrantKind,
        credit_usd: Decimal,
        *,
        actor_display: str,
        amount_paid_usd: Decimal | None = None,
        external_ref: str | None = None,
        note: str | None = None,
    ) -> None:
        session.add(
            OrganizationCreditGrant(
                organization_id=organization_id,
                kind=kind,
                credit_usd=credit_usd,
                amount_paid_usd=amount_paid_usd,
                external_ref=external_ref,
                actor_display=actor_display,
                note=note,
            )
        )
        session.flush()

    @staticmethod
    def _credit_total(session: Session, organization_id: UUID) -> Decimal:
        total = session.scalar(
            select(func.coalesce(func.sum(OrganizationCreditGrant.credit_usd), 0)).where(
                col(OrganizationCreditGrant.organization_id) == organization_id
            )
        )
        return Decimal(total or 0)

    @staticmethod
    def _already_granted(session: Session, external_ref: str) -> bool:
        return (
            session.exec(
                select(OrganizationCreditGrant.id).where(col(OrganizationCreditGrant.external_ref) == external_ref)
            ).first()
            is not None
        )

    @staticmethod
    def _locked(session: Session, organization_id: UUID) -> Organization | None:
        return session.exec(
            select(Organization).where(col(Organization.id) == organization_id).with_for_update()
        ).first()

    def _write_llm_budgets(
        self,
        session: Session,
        organization: Organization,
        *,
        ceiling_usd: float,
        window: str,
        own_limit_usd: float | None,
        actor: ActorIdentity,
        actor_display: str,
        reason: str | None,
    ) -> tuple[Organization, list[UUID]]:
        """Persist the limits on a locked row and stage their change Event in the same
        transaction, so a limit can never move without its audit record. The previous
        values are read under that lock, so two concurrent changes cannot both report
        the same "before"."""
        organization_id = organization.id
        previous_ceiling = organization.llm_budget_usd
        previous_own = organization.llm_own_budget_usd
        organization.llm_budget_usd = ceiling_usd
        organization.llm_budget_duration = window
        organization.llm_own_budget_usd = own_limit_usd
        organization.updated_at = datetime.now(UTC)
        session.add(organization)
        session.flush()

        event = EVENT_REGISTRY.build_event(
            event_name=ORGANIZATION_LLM_BUDGET_CHANGED,
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
                "ceiling_usd": ceiling_usd,
                "previous_ceiling_usd": previous_ceiling,
                "own_limit_usd": own_limit_usd,
                "previous_own_limit_usd": previous_own,
                "window": window,
                "reason": reason,
                "actor_display": actor_display,
                "subject_display": organization.name,
            },
        )
        self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
        delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
        session.commit()
        return organization, delivery_ids

    def get(self, organization_id: UUID) -> Organization | None:
        return self.delegate.find_by_id(Organization, organization_id)

    def owns_active_trial(self, user_id: UUID) -> bool:
        with Session(self.delegate.engine) as session:
            owned = session.exec(
                select(Organization.id)
                .join(OrganizationUser, col(OrganizationUser.organization_id) == Organization.id)
                .where(
                    col(OrganizationUser.user_id) == user_id,
                    col(OrganizationUser.role) == OrganizationRole.OWNER,
                    col(Organization.is_trial).is_(True),
                )
            ).first()
            return owned is not None

    def count_trials(self) -> int:
        """Organizations still on a trial: ended or expired trials and deleted Organizations
        don't count."""
        with Session(self.delegate.engine) as session:
            query = (
                select(func.count())
                .select_from(Organization)
                .where(col(Organization.is_trial).is_(True), col(Organization.trial_expired_at).is_(None))
            )
            return session.scalar(query) or 0

    def first_created_by(self, user_id: UUID) -> Organization | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(Organization)
                .where(col(Organization.created_by_user_id) == user_id)
                .order_by(col(Organization.created_at))
            ).first()

    def set_agent_limit_with_event(
        self, organization_id: UUID, agent_limit: int | None, *, actor: ActorIdentity, actor_display: str
    ) -> tuple[Organization, list[UUID]] | None:
        """Set how many Agents the Organization may run, with its audit Event in the same
        commit. No Event when nothing changed. None when the Organization does not exist."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            organization = self._locked(session, organization_id)
            if organization is None:
                return None
            previous = organization.agent_limit
            if previous == agent_limit:
                return organization, []
            organization.agent_limit = agent_limit
            organization.updated_at = datetime.now(UTC)
            session.add(organization)
            session.flush()
            event = EVENT_REGISTRY.build_event(
                event_name=ORGANIZATION_AGENT_LIMIT_CHANGED,
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
                    "agent_limit": agent_limit,
                    "previous_agent_limit": previous,
                    "actor_display": actor_display,
                    "subject_display": organization.name,
                },
            )
            self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return organization, delivery_ids

    def expire_trial_with_event(self, organization_id: UUID) -> list[UUID]:
        """Mark a trial that has run out of credit as expired, with its audit Event in the
        same commit. Nothing, and no Event, for an Organization that is not a trial or
        has already expired."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            organization = self._locked(session, organization_id)
            if organization is None or not organization.is_trial or organization.trial_expired_at is not None:
                return []
            organization.trial_expired_at = datetime.now(UTC)
            session.add(organization)
            session.flush()
            event = EVENT_REGISTRY.build_event(
                event_name=ORGANIZATION_TRIAL_EXPIRED,
                schema_version=1,
                occurred_at=datetime.now(UTC),
                organization_id=organization_id,
                actor=ActorIdentity(type=ActorIdentityType.SYSTEM, id="trial-expiry"),
                subject=SubjectIdentity(
                    type=SubjectIdentityType.ORGANIZATION,
                    id=organization_id,
                    organization_id=organization_id,
                ),
                correlation_id=uuid4(),
                payload={
                    "organization_id": organization_id,
                    "actor_display": "Trial credit used up",
                    "subject_display": organization.name,
                },
            )
            self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return delivery_ids

    def end_trial_with_event(
        self, organization_id: UUID, *, actor: ActorIdentity, actor_display: str
    ) -> tuple[Organization, list[UUID]] | None:
        """Make a trial an ordinary Organization, with its audit Event in the same commit.
        None when the Organization does not exist; no Event when it was not a trial."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            organization = self._locked(session, organization_id)
            if organization is None:
                return None
            if not organization.is_trial:
                return organization, []
            organization.is_trial = False
            organization.trial_expired_at = None
            organization.updated_at = datetime.now(UTC)
            session.add(organization)
            # The trial's creator may now create Organizations of their own.
            creator = session.get(User, organization.created_by_user_id) if organization.created_by_user_id else None
            if creator is not None and creator.trial_ended_at is None:
                creator.trial_ended_at = organization.updated_at
                session.add(creator)
            session.flush()
            event = EVENT_REGISTRY.build_event(
                event_name=ORGANIZATION_TRIAL_ENDED,
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
                    "actor_display": actor_display,
                    "subject_display": organization.name,
                },
            )
            self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return organization, delivery_ids

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
        actor: ActorIdentity,
        *,
        opening_credit_usd: Decimal | None = None,
        opening_credit_kind: CreditGrantKind = CreditGrantKind.ADJUSTMENT,
        in_transaction: Callable[[Session], None] | None = None,
    ) -> tuple[Organization, list[UUID]]:
        """Create the Organization and its creator's Owner Membership, staging its creation
        Event; with `opening_credit_usd`, also open its credit ledger, all in one commit.
        `in_transaction` runs inside it, after the quota check, and may raise to refuse."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            # Serialize creation attempts for one user. Without this lock, two
            # concurrent requests could both observe one remaining quota slot.
            creator = session.exec(select(User).where(col(User.id) == creator_id).with_for_update()).one()
            created_count = session.scalar(
                select(func.count()).select_from(Organization).where(col(Organization.created_by_user_id) == creator.id)
            )
            if (created_count or 0) >= creation_limit:
                raise OrganizationCreationLimitReached(creation_limit)
            if in_transaction is not None:
                in_transaction(session)

            session.add(organization)
            session.flush()
            session.add(
                OrganizationUser(
                    user_id=creator.id,
                    organization_id=organization.id,
                    role=OrganizationRole.OWNER,
                )
            )
            if opening_credit_usd is not None:
                self._add_credit_grant(
                    session,
                    organization.id,
                    opening_credit_kind,
                    opening_credit_usd,
                    actor_display="Opening balance",
                )
            delivery_ids = self.stage_organization_created(session, organization, actor)
            session.commit()
            return organization, delivery_ids

    def stage_organization_created(
        self, session: Session, organization: Organization, actor: ActorIdentity
    ) -> list[UUID]:
        event = EVENT_REGISTRY.build_event(
            event_name=ORGANIZATION_CREATED,
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=organization.id,
            actor=actor,
            subject=SubjectIdentity(
                type=SubjectIdentityType.ORGANIZATION,
                id=organization.id,
                organization_id=organization.id,
            ),
            correlation_id=uuid4(),
            payload={"organization_id": organization.id, "created_by_user_id": organization.created_by_user_id},
        )
        self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
        return self.outbox_repository.delivery_ids_for_event(session, event.event_id)

    def delete(self, organization_id: UUID, before_delete: Callable[[Session], None] | None = None) -> bool:
        with Session(self.delegate.engine) as session:
            if before_delete:
                before_delete(session)
            organization = session.get(Organization, organization_id)
            if organization is None:
                return False
            session.delete(organization)
            session.commit()
            return True

    def delete_with_event(
        self,
        organization_id: UUID,
        actor: ActorIdentity,
        before_delete: Callable[[Session], None] | None = None,
    ) -> list[UUID]:
        with Session(self.delegate.engine) as session:
            if before_delete:
                before_delete(session)
            organization = session.exec(
                select(Organization).where(col(Organization.id) == organization_id).with_for_update()
            ).first()
            if organization is None:
                return []
            event = EVENT_REGISTRY.build_event(
                event_name=ORGANIZATION_DELETED,
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
                payload={"organization_id": organization_id},
            )
            self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = self.outbox_repository.delivery_ids_for_event(session, event.event_id)
            session.delete(organization)
            session.commit()
            return delivery_ids
