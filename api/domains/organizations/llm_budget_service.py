"""An Organization's LLM spend limit: setting it, enforcing coverage, and noticing
when it runs out.

Split from OrganizationService, which had grown to hold membership, model
allowlists and this. The two share only the Organization row.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from injector import inject
from sqlmodel import Session

from api.core.config import get_config
from api.domains.agent_settings.service import AgentSettingsService
from api.domains.agents.llm_budget import AgentLlmBudgetService
from api.domains.auth.models import CurrentUserContext
from api.domains.events import (
    ActorIdentity,
    ActorIdentityType,
    EventDeliveryDispatcher,
    SubjectIdentity,
    SubjectIdentityType,
    resolve_actor_identity,
)
from api.domains.events.catalog import (
    EVENT_REGISTRY,
    ORGANIZATION_LLM_BUDGET_EXHAUSTED,
    ORGANIZATION_LLM_BUDGET_THRESHOLD_REACHED,
)
from api.domains.organizations.models import (
    AgentLlmCoverageRead,
    AgentLlmEnrollment,
    Organization,
    OrganizationLlmBudgetRead,
    OrganizationLlmBudgetState,
    OrganizationLlmCoverageRead,
    PlatformOrganizationRead,
)
from api.domains.organizations.repository import OrganizationRepository
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError, LiteLLMKeyNotFound

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BudgetCrossing:
    """One Organization crossing one threshold, and the row to record it against.

    A dataclass rather than a dict so the row travels openly instead of being
    smuggled in under a key the caller has to remember to remove.
    """

    organization: Organization
    threshold_percent: int
    spend_usd: float
    limit_usd: float
    renews_at: str | None


def _parse_timestamp(value: object) -> datetime | None:
    """LiteLLM returns ISO-8601; a value we cannot parse is stored as unknown rather
    than guessed at."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@inject
@dataclass
class OrganizationLlmBudgetService:
    organization_repository: OrganizationRepository
    agent_budgets: AgentLlmBudgetService
    agent_settings: AgentSettingsService
    litellm: LiteLLMClient
    permission_policy: PermissionPolicy
    event_delivery_dispatcher: EventDeliveryDispatcher

    def _litellm_configured(self) -> bool:
        config = get_config()
        return bool(config.litellm_base_url and config.litellm_secret_name)

    def reconcile_llm_budgets(self) -> None:
        """Repair drift between stored budgets and the proxy.

        Best effort by design. A budget is pushed to LiteLLM when an administrator
        sets it, so a failure here delays repair rather than losing a policy — and
        must never stop the API from serving.
        """
        if not self._litellm_configured():
            return
        policies = self.organization_repository.list_budget_policies()
        failures = 0
        for organization_id, budget, duration in policies:
            try:
                self._record_renewal(
                    organization_id, self.litellm.apply_team_budget(str(organization_id), budget, duration)
                )
            except Exception:
                failures += 1
                logger.exception("LiteLLM budget reconciliation failed for Organization %s", organization_id)
        if failures:
            logger.error("Organization LiteLLM budget reconciliation: %s of %s failed", failures, len(policies))
        else:
            logger.info("Organization LiteLLM budgets reconciled (%s organizations)", len(policies))
        # After the teams: an Agent limit is held beneath its Organization's, so the
        # Organization's must be right first.
        self.agent_budgets.reconcile_key_budgets()

    def set_llm_budget(
        self,
        organization_id: UUID,
        budget_usd: float,
        budget_duration: str | None,
        context: CurrentUserContext,
    ) -> PlatformOrganizationRead:
        """Set an Organization's ceiling and mirror it onto its LiteLLM team.

        Lowering the ceiling beneath the Organization's own limit pulls that limit
        down with it, and every Agent limit beneath that in turn: an Organization is
        never bound by a number higher than the platform's. The rows are saved first
        and are authoritative; if the proxy write fails the administrator is told,
        and the stored intent survives for the reconciler to apply.
        """
        organization = self._organization_or_404(organization_id)
        own = organization.llm_own_budget_usd
        lowered = own is not None and own > budget_usd
        self._store_and_apply(
            organization,
            ceiling_usd=budget_usd,
            # Omitted keeps the configured window: changing only the amount must not
            # silently reschedule the Organization's renewal date.
            window=budget_duration or organization.llm_budget_duration,
            own_limit_usd=budget_usd if lowered else own,
            context=context,
            reason="Lowered to fit within the platform's spend limit." if lowered else None,
        )
        return self._platform_read_or_404(organization_id)

    def set_own_llm_budget(
        self, organization_id: UUID, budget_usd: float | None, context: CurrentUserContext
    ) -> OrganizationLlmBudgetRead:
        """The Organization's own limit, beneath the platform's.

        Refused rather than clamped above the ceiling: storing less than was asked
        for would leave the caller believing a number that is not in force.
        """
        self.permission_policy.require(
            context,
            organization_id,
            PermissionKey.LLM_BUDGET_MANAGE,
            detail="You don't have permission to change this organization's spend limit.",
        )
        organization = self._organization_or_404(organization_id)
        if budget_usd is not None and budget_usd > organization.llm_budget_usd:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Your organization's spend limit can't be more than the "
                    f"${organization.llm_budget_usd:,.2f} your plan allows."
                ),
            )
        if budget_usd != organization.llm_own_budget_usd:
            self._store_and_apply(
                organization,
                ceiling_usd=organization.llm_budget_usd,
                window=organization.llm_budget_duration,
                own_limit_usd=budget_usd,
                context=context,
                reason=None,
            )
        return self.get_organization_llm_budget(organization_id, context)

    def provision_team(self, organization_id: UUID) -> None:
        """Create a new Organization's team with its limit already on it.

        Best effort: the Organization is already committed, key generation provisions
        the team again if this fails, and the reconciler applies the stored limit.
        """
        if not self._litellm_configured():
            return
        organization = self.organization_repository.get(organization_id)
        if organization is None:
            return
        try:
            renews_at = self.litellm.apply_team_budget(
                str(organization_id), organization.effective_llm_budget_usd, organization.llm_budget_duration
            )
        except Exception as exc:
            logger.error(
                "LiteLLM team provisioning deferred for Organization %s (%s)", organization_id, type(exc).__name__
            )
            return
        self._record_renewal(organization_id, renews_at)

    def _store_and_apply(
        self,
        organization: Organization,
        *,
        ceiling_usd: float,
        window: str,
        own_limit_usd: float | None,
        context: CurrentUserContext,
        reason: str | None,
    ) -> None:
        organization_id = organization.id
        before = self.agent_budgets.key_limits(organization_id)
        actor = resolve_actor_identity(context, organization_id)
        actor_display = context.user.full_name or context.user.email
        result = self.organization_repository.set_llm_budgets_with_event(
            organization_id,
            ceiling_usd=ceiling_usd,
            window=window,
            own_limit_usd=own_limit_usd,
            actor=actor,
            actor_display=actor_display,
            reason=reason,
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization {organization_id} not found"
            )
        stored, delivery_ids = result
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)

        if self._litellm_configured():
            try:
                renews_at = self.litellm.apply_team_budget(
                    str(organization_id), stored.effective_llm_budget_usd, stored.llm_budget_duration
                )
            except Exception as exc:
                logger.exception("Failed to apply LLM budget for Organization %s", organization_id)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Spend limit saved, but it could not be applied yet. It will be retried automatically.",
                ) from exc
            self._record_renewal(organization_id, renews_at)
        self.agent_settings.lower_default_agent_llm_budget(
            organization_id, stored.effective_llm_budget_usd, actor=actor, actor_display=actor_display
        )
        # Agents follow the Organization: any limit above the new one comes down, and
        # every key whose limit moved is rewritten. A key that cannot be updated now is
        # left to the reconciler rather than failing a change that is already saved.
        self.agent_budgets.fit_to_organization(organization_id, before=before, actor=actor, actor_display=actor_display)

    def _record_renewal(self, organization_id: UUID, renews_at: object) -> None:
        """The team is read whenever its limit is written, so its renewal date is known
        then, not only after the next scheduled refresh. An unreadable date leaves the
        previous one alone."""
        parsed = _parse_timestamp(renews_at)
        if parsed is not None:
            self.organization_repository.set_llm_budget_renews_at(organization_id, parsed)

    def _organization_or_404(self, organization_id: UUID) -> Organization:
        organization = self.organization_repository.get(organization_id)
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )
        return organization

    @staticmethod
    def _alert_thresholds() -> list[int]:
        """Deployment-configured. Shared between the alerting pass and the
        Organization's own view so a banner and an email can never disagree about
        what counts as a warning."""
        return get_config().llm_budget_alert_thresholds

    def get_organization_llm_budget(
        self, organization_id: UUID, context: CurrentUserContext
    ) -> OrganizationLlmBudgetRead:
        """The Organization's own view of its limit, served from the stored snapshot.

        Deliberately not a live proxy read: this feeds surfaces on ordinary page loads,
        and an external call there would add latency and a failure mode to pages that
        have nothing to do with budgets.
        """
        self.permission_policy.require_organization(
            context,
            organization_id,
            PermissionKey.COST_READ,
            detail="You don't have permission to view organization costs.",
        )
        organization = self._organization_or_404(organization_id)
        limit = organization.effective_llm_budget_usd
        spend = organization.llm_spend_usd
        observed = spend is not None and organization.llm_spend_observed_at is not None
        if not observed:
            state = OrganizationLlmBudgetState.UNKNOWN
        elif spend >= limit:
            state = OrganizationLlmBudgetState.EXHAUSTED
        elif limit > 0 and spend >= limit * min(self._alert_thresholds()) / 100:
            state = OrganizationLlmBudgetState.WARNING
        else:
            state = OrganizationLlmBudgetState.OK
        return OrganizationLlmBudgetRead(
            state=state,
            limit_usd=limit,
            ceiling_usd=organization.llm_budget_usd,
            own_limit_usd=organization.llm_own_budget_usd,
            window=organization.llm_budget_duration,
            spend_usd=spend if observed else None,
            renews_at=organization.llm_budget_renews_at,
            can_manage=self.permission_policy.resolve(context, organization_id, PermissionKey.LLM_BUDGET_MANAGE)
            is not None,
        )

    def check_llm_budget_thresholds(self) -> list[BudgetCrossing]:
        """Refresh each capped Organization's spend snapshot and report new crossings.

        Informational only. A limit is enforced by the proxy in the request path; this
        pass exists so a human hears about it, and no polling interval can stop an
        Organization spending past its cap in between runs.
        """
        if not self._litellm_configured():
            return []
        fired: list[BudgetCrossing] = []
        for organization in self.organization_repository.list_capped_organizations():
            try:
                crossings = self._check_one_budget(organization)
            except Exception:
                # One unreadable Organization must not cost every other one its check.
                logger.exception("LLM budget threshold check failed for Organization %s", organization.id)
                continue
            for crossing in crossings:
                # Recorded only once the notification is staged. The other order means
                # a failed publish marks the threshold alerted and it never fires
                # again for this window — the alert is lost, not delayed.
                if not self._publish_budget_crossing(crossing):
                    continue
                crossing.organization.llm_alerted_threshold = crossing.threshold_percent
                self.organization_repository.save(crossing.organization)
                fired.append(crossing)
        if fired:
            logger.info("Organization LLM budget thresholds crossed: %s", len(fired))
        self.agent_budgets.check_llm_budget_thresholds()
        return fired

    def _publish_budget_crossing(self, crossing: BudgetCrossing) -> bool:
        """Staged through the outbox like any other domain event, so a failed
        notification is retried and shows up in the Event Delivery Monitor rather than
        vanishing."""
        organization_id = crossing.organization.id
        event_name = (
            ORGANIZATION_LLM_BUDGET_EXHAUSTED
            if crossing.threshold_percent >= 100
            else ORGANIZATION_LLM_BUDGET_THRESHOLD_REACHED
        )
        try:
            with Session(self.organization_repository.delegate.engine, expire_on_commit=False) as session:
                event = EVENT_REGISTRY.build_event(
                    event_name=event_name,
                    schema_version=1,
                    occurred_at=datetime.now(UTC),
                    organization_id=organization_id,
                    actor=ActorIdentity(type=ActorIdentityType.SYSTEM, id="llm-budget-alerts"),
                    subject=SubjectIdentity(
                        type=SubjectIdentityType.ORGANIZATION,
                        id=organization_id,
                        organization_id=organization_id,
                    ),
                    correlation_id=uuid4(),
                    payload={
                        "organization_id": organization_id,
                        "threshold_percent": crossing.threshold_percent,
                        "spend_usd": crossing.spend_usd,
                        "limit_usd": crossing.limit_usd,
                        "renews_at": crossing.renews_at,
                        "subject_display": crossing.organization.name,
                    },
                )
                self.organization_repository.outbox_repository.stage(
                    session=session, registry=EVENT_REGISTRY, event=event
                )
                delivery_ids = self.organization_repository.outbox_repository.delivery_ids_for_event(
                    session, event.event_id
                )
                session.commit()
            self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
        except Exception:
            # The snapshot is already saved; the threshold is deliberately left
            # unrecorded so the next pass retries this same crossing.
            logger.exception("Failed to publish LLM budget alert for Organization %s", organization_id)
            return False
        return True

    def _check_one_budget(self, organization: Organization) -> list[BudgetCrossing]:
        status_ = self.litellm.get_team_budget_status(str(organization.id))
        limit = organization.effective_llm_budget_usd
        if status_ is None or status_.get("spend") is None or limit is None:
            # Leave the previous snapshot alone: "we could not read it" is not the same
            # as "nothing has been spent", and overwriting would assert the latter.
            return []

        spend = float(status_["spend"])
        renews_at = status_.get("renews_at")
        organization.llm_spend_usd = spend
        organization.llm_spend_observed_at = datetime.now(UTC)
        organization.llm_budget_renews_at = _parse_timestamp(renews_at)

        # The key spans the window and the limit, so both a renewal and a limit change
        # re-arm the thresholds rather than leaving the Organization permanently quiet.
        alert_key = f"{renews_at}|{limit}"
        if organization.llm_alert_key != alert_key:
            organization.llm_alert_key = alert_key
            organization.llm_alerted_threshold = None

        reached = [t for t in self._alert_thresholds() if limit > 0 and spend >= limit * t / 100]
        reached = reached or ([100] if limit == 0 else [])
        highest = max(reached, default=None)
        already = organization.llm_alerted_threshold
        fired: list[BudgetCrossing] = []
        if highest is not None and (already is None or highest > already):
            fired.append(
                BudgetCrossing(
                    organization=organization,
                    threshold_percent=highest,
                    spend_usd=spend,
                    limit_usd=limit,
                    renews_at=renews_at,
                )
            )
        self.organization_repository.save(organization)
        return fired

    def get_llm_coverage(self, organization_id: UUID) -> OrganizationLlmCoverageRead:
        """Which of this Organization's Agents a team budget would actually bind.

        Read from the proxy on every call. A cached answer would keep claiming
        coverage after someone detached a key by hand, which is the one lie this
        surface must not tell.
        """
        return self._coverage(organization_id, enroll=False)

    def enroll_llm_keys(self, organization_id: UUID) -> OrganizationLlmCoverageRead:
        """Attach this Organization's existing Agent keys to its LiteLLM team.

        Idempotent, and safe to re-run: keys already in the team are skipped and keys
        in another team are reported rather than moved. Partial success is a normal
        outcome, so the caller gets a census instead of a success flag.
        """
        if not self._litellm_configured():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="LiteLLM is not configured for this deployment",
            )
        try:
            self.litellm.ensure_team_exists(str(organization_id))
        except LiteLLMError as exc:
            # Without a team there is nothing to enroll into, so this is the one
            # failure that stops the whole run rather than landing in the census.
            logger.warning("Cannot enroll Organization %s: its LiteLLM team is unavailable", organization_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="The LLM proxy is unreachable, so agents could not be enrolled",
            ) from exc
        return self._coverage(organization_id, enroll=True)

    def _coverage(self, organization_id: UUID, *, enroll: bool) -> OrganizationLlmCoverageRead:
        if not self.organization_repository.get(organization_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )
        team_id = str(organization_id)
        config = get_config()
        uncovered: list[AgentLlmCoverageRead] = []
        enrolled = newly_enrolled = 0

        credentials = self.agent_budgets.llm_credentials(organization_id)
        for agent_id, agent_name, encrypted_key in credentials:
            status_, was_enrolled = self._agent_coverage(
                encrypted_key, team_id, config.agent_token_encryption_key, enroll=enroll
            )
            if status_ is AgentLlmEnrollment.ENROLLED:
                enrolled += 1
                newly_enrolled += 1 if was_enrolled else 0
            else:
                uncovered.append(AgentLlmCoverageRead(agent_id=agent_id, agent_name=agent_name, status=status_))
        budget_status = self._team_budget_status(team_id)
        return OrganizationLlmCoverageRead(
            total_agents=len(credentials),
            enrolled_agents=enrolled,
            uncovered=uncovered,
            newly_enrolled=newly_enrolled,
            spend_usd=budget_status.get("spend"),
            renews_at=budget_status.get("renews_at"),
        )

    def _team_budget_status(self, team_id: str) -> dict:
        """An unreadable proxy leaves spend unknown. Rendering it as $0 spent is the
        exact defect the cost-tracking rewrite existed to remove."""
        try:
            return self.litellm.get_team_budget_status(team_id) or {}
        except Exception:
            logger.warning("Could not read LiteLLM team spend for %s", team_id)
            return {}

    def _agent_coverage(
        self, encrypted_key: str, team_id: str, encryption_key: str, *, enroll: bool
    ) -> tuple[AgentLlmEnrollment, bool]:
        """Never lets one Agent's failure end the sweep, and never logs the key."""
        try:
            key = decrypt_token(encrypted_key, encryption_key)
        except Exception:
            logger.warning("Could not decrypt the stored LiteLLM key for an Agent in team %s", team_id)
            return AgentLlmEnrollment.UNREADABLE, False
        try:
            current = self.litellm.get_key_team(key)
            if current == team_id:
                return AgentLlmEnrollment.ENROLLED, False
            if current:
                return AgentLlmEnrollment.OTHER_TEAM, False
            if not enroll:
                return AgentLlmEnrollment.UNENROLLED, False
            # The membership was just read above; passing it spares a repeat lookup.
            self.litellm.attach_key_to_team(key, team_id, current_team=current)
            return AgentLlmEnrollment.ENROLLED, True
        except LiteLLMKeyNotFound:
            return AgentLlmEnrollment.UNKNOWN_KEY, False
        except Exception:
            # Deliberately broad. Reading the master key goes through the Kubernetes
            # API, which fails with urllib3 errors rather than LiteLLMError; letting
            # those escape turns an honest "could not check" census into a 500.
            logger.warning("LiteLLM key enrollment check failed for an Agent in team %s", team_id)
            return AgentLlmEnrollment.UNREADABLE, False

    def _platform_read_or_404(self, organization_id: UUID) -> PlatformOrganizationRead:
        organization_read = self.organization_repository.get_platform_read(organization_id)
        if organization_read is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )
        return organization_read
