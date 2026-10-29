from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from injector import inject, singleton

from api.domains.organizations.models import CreditGrantKind, CreditGrantRead, PlatformCreditGrantRead
from api.domains.organizations.repository import OrganizationRepository
from api.infrastructure.litellm.client import ONE_OFF_BUDGET_WINDOW
from api.infrastructure.shared.models import PaginatedItems, Pagination

# Refusing a limit beneath an Organization's balance. No straight apostrophes: settings
# surfaces render a single-quoted run of an error detail as a code identifier.
ON_CREDIT_LIMIT_REFUSED = "This organization runs on credit, so its balance is its only spend limit."


@dataclass(frozen=True)
class OrganizationLlmLimit:
    """The limit in force on an Organization's team, and the window it renews on.

    Agent limits are held beneath `limit_usd` and share `window`, so the Organization
    and every one of its Agents renew at the same moment.
    """

    limit_usd: float
    window: str
    # When the Organization's window next renews — and so every Agent key's, since
    # they share it. None until the proxy has reported one.
    renews_at: datetime | None = None

    @property
    def runs_on_credit(self) -> bool:
        """Credit never renews, so any limit beneath it would be a lifetime cap that no
        top-up could lift: on credit the Organization's balance is the only limit."""
        return self.window == ONE_OFF_BUDGET_WINDOW


@dataclass(frozen=True)
class OrganizationCredit:
    """An Organization's credit as of its last spend snapshot."""

    name: str
    runs_on_credit: bool
    credit_usd: float
    # None until spend has been observed.
    spend_usd: float | None


@dataclass(frozen=True)
class RecordedCredit:
    """One change to an Organization's credit, found by its payment provider reference."""

    organization_id: UUID
    credit_usd: Decimal
    # What was paid for it, for a purchase.
    amount_paid_usd: Decimal | None


@dataclass(frozen=True)
class OrganizationAgentLimit:
    """An Organization's own Agent limit, and whether a trial's default applies."""

    own: int | None
    is_trial: bool

    def in_force(self, *, trial_limit: Callable[[], int], default: Callable[[], int]) -> int:
        """Its own limit, else the trial setting for a trial, else the platform's
        default. Each default is read only when it is the one that applies."""
        if self.own is not None:
            return self.own
        return trial_limit() if self.is_trial else default()


@inject
@singleton
@dataclass
class OrganizationLookupService:
    """Read-only organization lookups for other domains' services.

    Lives in its own module, importing nothing but the repository, so that
    services which OrganizationService itself depends on (e.g. AgentService,
    via the delete-org guardrail) can inject it without an import cycle.
    """

    repository: OrganizationRepository

    def get_name(self, organization_id: UUID) -> str:
        organization = self.repository.get(organization_id)
        return organization.name if organization else ""

    def get_allowed_models(self, organization_id: UUID) -> list[str] | None:
        """The org's per-org model allowlist, or None if the org doesn't exist.

        None (missing org) is distinct from [] (org exists but allows nothing),
        so callers can raise 404 vs. reject the model accordingly.
        """
        organization = self.repository.get(organization_id)
        return organization.allowed_models if organization else None

    def first_created_by(self, user_id: UUID) -> UUID | None:
        """The first Organization a user created: a self-signed-up user's trial."""
        organization = self.repository.first_created_by(user_id)
        return organization.id if organization else None

    def count_trials(self) -> int:
        """How many Organizations are on a trial right now."""
        return self.repository.count_trials()

    def is_trial(self, organization_id: UUID) -> bool:
        organization = self.repository.get(organization_id)
        return organization is not None and organization.is_trial

    def get_agent_limit(self, organization_id: UUID) -> OrganizationAgentLimit | None:
        """None when the Organization does not exist."""
        organization = self.repository.get(organization_id)
        if organization is None:
            return None
        return OrganizationAgentLimit(own=organization.agent_limit, is_trial=organization.is_trial)

    def get_credit(self, organization_id: UUID) -> OrganizationCredit | None:
        """None when the Organization does not exist."""
        organization = self.repository.get(organization_id)
        if organization is None:
            return None
        return OrganizationCredit(
            name=organization.name,
            runs_on_credit=organization.runs_on_credit,
            credit_usd=organization.llm_budget_usd,
            spend_usd=organization.llm_spend_usd,
        )

    def list_credit_grants(self, organization_id: UUID) -> list[CreditGrantRead]:
        """Every change to the Organization's credit, oldest first."""
        return [CreditGrantRead.model_validate(grant) for grant in self.repository.list_credit_grants(organization_id)]

    def list_all_credit_grants(
        self,
        pagination: Pagination,
        *,
        kind: str | None = None,
        organization_id: UUID | None = None,
    ) -> PaginatedItems[PlatformCreditGrantRead]:
        """Every Organization's changes to its credit, newest first; `kind` narrows it to
        one kind of change, by its value."""
        return self.repository.list_all_credit_grants(
            pagination, kind=CreditGrantKind(kind) if kind else None, organization_id=organization_id
        )

    def find_credit_grant(self, external_ref: str) -> RecordedCredit | None:
        """The grant recorded under a payment provider's reference, if any."""
        grant = self.repository.get_credit_grant_by_ref(external_ref)
        if grant is None:
            return None
        return RecordedCredit(
            organization_id=grant.organization_id, credit_usd=grant.credit_usd, amount_paid_usd=grant.amount_paid_usd
        )

    def get_llm_limit(self, organization_id: UUID) -> OrganizationLlmLimit | None:
        """None when the Organization does not exist."""
        organization = self.repository.get(organization_id)
        if organization is None:
            return None
        return OrganizationLlmLimit(
            limit_usd=organization.effective_llm_budget_usd,
            window=organization.llm_budget_duration,
            renews_at=organization.llm_budget_renews_at,
        )
