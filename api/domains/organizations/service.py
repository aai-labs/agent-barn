import fnmatch
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlmodel import Session, select

from api.core.config import get_config
from api.domains.agent_settings.lookup import AgentSettingsLookupService
from api.domains.agents.repository import AgentRepository
from api.domains.agents.service import _OPENROUTER_MODEL_PREFIX, AgentService, is_model_allowed
from api.domains.auth.models import CurrentUserContext
from api.domains.events import (
    ActorIdentity,
    ActorIdentityType,
    EventDelivery,
    EventDeliveryDispatcher,
    SubjectIdentity,
    SubjectIdentityType,
    resolve_actor_identity,
)
from api.domains.events.catalog import (
    EVENT_REGISTRY,
    ORGANIZATION_LLM_BUDGET_EXHAUSTED,
    ORGANIZATION_LLM_BUDGET_THRESHOLD_REACHED,
    ORGANIZATION_MODEL_ALLOWLIST_CHANGED,
)
from api.domains.organizations.exceptions import OrganizationCreationLimitReached
from api.domains.organizations.models import (
    AgentLlmCoverageRead,
    AgentLlmEnrollment,
    Organization,
    OrganizationCreate,
    OrganizationFilter,
    OrganizationLlmBudgetRead,
    OrganizationLlmBudgetState,
    OrganizationLlmCoverageRead,
    OrganizationRead,
    OrganizationUpdate,
    PlatformOrganizationRead,
)
from api.domains.organizations.repository import OrganizationRepository
from api.domains.rbac.catalog import ORG_OWNER_ONLY_ROLES, PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError, LiteLLMKeyNotFound
from api.infrastructure.shared.models import PaginatedItems, Pagination

logger = logging.getLogger(__name__)


def _parse_timestamp(value: str | None) -> datetime | None:
    """LiteLLM returns ISO-8601; a value we cannot parse is stored as unknown rather
    than guessed at."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _and_list(items: list[str]) -> str:
    """Renders "a", "a and b", or "a, b and c" for naming things back to a user."""
    if len(items) <= 2:
        return " and ".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


@inject
@singleton
@dataclass
class OrganizationService:
    organization_repository: OrganizationRepository
    litellm: LiteLLMClient
    agent_service: AgentService
    permission_policy: PermissionPolicy
    event_delivery_dispatcher: EventDeliveryDispatcher
    agent_settings_lookup: AgentSettingsLookupService
    agent_repository: AgentRepository

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
                self.litellm.apply_team_budget(str(organization_id), budget, duration)
            except Exception:
                failures += 1
                logger.exception("LiteLLM budget reconciliation failed for Organization %s", organization_id)
        if failures:
            logger.error("Organization LiteLLM budget reconciliation: %s of %s failed", failures, len(policies))
        else:
            logger.info("Organization LiteLLM budgets reconciled (%s organizations)", len(policies))

    # Matches LiteLLM's own convention: a 30-day interval, not a calendar month.
    DEFAULT_BUDGET_DURATION = "30d"

    def set_llm_budget(
        self,
        organization_id: UUID,
        budget_usd: float | None,
        budget_duration: str | None,
    ) -> PlatformOrganizationRead:
        """Store an Organization's spend ceiling and mirror it onto its LiteLLM team.

        The row is authoritative and is saved first: if the proxy write fails the
        administrator is told, while the stored intent survives for the reconciler
        to apply. Losing the setting because the proxy blinked would be worse.
        """
        organization = self.organization_repository.get(organization_id)
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )
        organization.llm_budget_usd = budget_usd
        # Falls back to the window already configured before the default: changing only
        # the amount must not silently reschedule the Organization's renewal date.
        organization.llm_budget_duration = (
            (budget_duration or organization.llm_budget_duration or self.DEFAULT_BUDGET_DURATION)
            if budget_usd is not None
            else None
        )
        self.organization_repository.save(organization)

        if not self._litellm_configured():
            return self._platform_read_or_404(organization_id)
        try:
            self.litellm.apply_team_budget(
                str(organization.id), organization.llm_budget_usd, organization.llm_budget_duration
            )
        except Exception as exc:
            logger.exception("Failed to apply LLM budget for Organization %s", organization_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Budget saved but the LLM proxy could not be updated; it will be retried automatically",
            ) from exc
        return self._platform_read_or_404(organization_id)

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
        organization = self.organization_repository.get(organization_id)
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )
        limit = organization.llm_budget_usd
        spend = organization.llm_spend_usd
        if limit is None:
            return OrganizationLlmBudgetRead(state=OrganizationLlmBudgetState.NONE)
        if spend is None or organization.llm_spend_observed_at is None:
            return OrganizationLlmBudgetRead(state=OrganizationLlmBudgetState.UNKNOWN, limit_usd=limit)
        if spend >= limit:
            state = OrganizationLlmBudgetState.EXHAUSTED
        elif limit > 0 and spend >= limit * min(self._alert_thresholds()) / 100:
            state = OrganizationLlmBudgetState.WARNING
        else:
            state = OrganizationLlmBudgetState.OK
        return OrganizationLlmBudgetRead(
            state=state,
            limit_usd=limit,
            spend_usd=spend,
            renews_at=organization.llm_budget_renews_at,
        )

    def check_llm_budget_thresholds(self) -> list[dict]:
        """Refresh each capped Organization's spend snapshot and report new crossings.

        Informational only. A limit is enforced by the proxy in the request path; this
        pass exists so a human hears about it, and no polling interval can stop an
        Organization spending past its cap in between runs.
        """
        if not self._litellm_configured():
            return []
        fired: list[dict] = []
        for organization in self.organization_repository.list_capped_organizations():
            try:
                crossings = self._check_one_budget(organization)
            except Exception:
                # One unreadable Organization must not cost every other one its check.
                logger.warning("LLM budget threshold check failed for Organization %s", organization.id)
                continue
            for crossing in crossings:
                self._publish_budget_crossing(crossing)
            fired.extend(crossings)
        if fired:
            logger.info("Organization LLM budget thresholds crossed: %s", len(fired))
        return fired

    def _publish_budget_crossing(self, crossing: dict) -> None:
        """Staged through the outbox like any other domain event, so a failed
        notification is retried and shows up in the Event Delivery Monitor rather than
        vanishing."""
        organization_id = crossing["organization_id"]
        event_name = (
            ORGANIZATION_LLM_BUDGET_EXHAUSTED
            if crossing["threshold_percent"] >= 100
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
                        "threshold_percent": crossing["threshold_percent"],
                        "spend_usd": crossing["spend_usd"],
                        "limit_usd": crossing["limit_usd"],
                        "renews_at": crossing["renews_at"],
                        "subject_display": crossing["organization_name"],
                    },
                )
                self.organization_repository.outbox_repository.stage(
                    session=session, registry=EVENT_REGISTRY, event=event
                )
                delivery_ids = list(
                    session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id))
                )
                session.commit()
            self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
        except Exception:
            # The snapshot is already saved; losing the notification is better than
            # losing the pass, and the next crossing will try again.
            logger.exception("Failed to publish LLM budget alert for Organization %s", organization_id)

    def _check_one_budget(self, organization: Organization) -> list[dict]:
        status_ = self.litellm.get_team_budget_status(str(organization.id))
        limit = organization.llm_budget_usd
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
        fired: list[dict] = []
        if highest is not None and (already is None or highest > already):
            organization.llm_alerted_threshold = highest
            fired.append(
                {
                    "organization_id": organization.id,
                    "organization_name": organization.name,
                    "threshold_percent": highest,
                    "spend_usd": spend,
                    "limit_usd": limit,
                    "renews_at": renews_at,
                }
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

        credentials = self.agent_repository.list_llm_credentials(organization_id)
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
            self.litellm.attach_key_to_team(key, team_id)
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

    def get_organization(self, organization_id: UUID, context: CurrentUserContext) -> OrganizationRead:
        # Any member (or a platform administrator in explicit Organization context) may
        # view the org; non-members are refused before the fetch so a 403-vs-404
        # difference can't confirm an org's existence.
        self._ensure_can_view_organization(organization_id, context)
        organization = self.organization_repository.get_read(organization_id)
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )
        return organization

    def get_platform_organization(self, organization_id: UUID) -> PlatformOrganizationRead:
        # Platform Administrators have no Membership in arbitrary Organizations, so this
        # deliberately skips _ensure_can_view_organization and returns the dedicated
        # Platform Oversight read model instead of the member-facing OrganizationRead.
        organization = self.organization_repository.get_platform_read(organization_id)
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )
        return organization

    @staticmethod
    def _bare_model(pattern: str) -> str:
        # Strip any litellm gateway prefix so patterns match the bare OpenRouter slug.
        return pattern.strip().lower().removeprefix("litellm/openrouter/")

    def _validate_allowed_models(self, allowed_models: list[str], existing: list[str] | None = None) -> None:
        if not allowed_models:
            return
        try:
            catalog = self.agent_service.openrouter.list_models()
        except Exception as e:
            # If the OpenRouter catalog is unavailable (e.g. no API key locally, a
            # transient outage), skip validation so admins can still configure the
            # allowlist — but log it so a silently-skipped validation is debuggable.
            logger.warning("OpenRouter catalog unavailable, skipping model allowlist validation: %s", e)
            return
        if not catalog:
            return
        # Entries already stored on the org are exempt from catalog validation:
        # a model OpenRouter has since removed ("orphaned") must be preservable on
        # save. Only newly-added patterns are checked against the live catalog.
        existing_bare = {self._bare_model(m) for m in (existing or [])}
        catalog_ids_lower = [m["id"].lower() for m in catalog]
        for pattern in allowed_models:
            bare = self._bare_model(pattern)
            if bare in existing_bare:
                continue
            if not any(fnmatch.fnmatch(cid, bare) for cid in catalog_ids_lower):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Model pattern '{pattern}' does not match any known models in the catalog.",
                )

    def _ensure_default_model_still_allowed(self, organization_id: UUID, allowed_models: list[str]) -> None:
        """Keeps the Organization's own default model inside its allowlist.

        The default is picked from the allowlist, so the only way it can leave is by
        editing the allowlist. Blocking that here means an Agent that inherits the
        default can never be pointed at a model the Organization disallows. An
        Organization following the platform default has nothing to protect: that value
        can change without any request to this API, so the invariant cannot be stated
        about it.
        """
        default_model = self.agent_settings_lookup.get_default_model(organization_id)
        if default_model is None:
            return
        if not is_model_allowed(default_model, allowed_models):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Model '{default_model.removeprefix(_OPENROUTER_MODEL_PREFIX)}' is the organization's "
                    "default Agent model and must stay in the "
                    "allowed model list. Change the default under Agent Settings first."
                ),
            )

    def _ensure_no_agent_is_pinned_to_a_removed_model(self, organization_id: UUID, allowed_models: list[str]) -> None:
        """Blocks removing a model that an Agent explicitly names.

        Removing it would not migrate that Agent onto anything — an explicit `model` is
        never rewritten by an allowlist edit — it would only make the Agent fail to start,
        because the start-time allowlist re-check applies precisely to explicit overrides.
        The failure would surface later, on a restart, far from the edit that caused it.

        Agents that inherit are unaffected and deliberately not consulted: they follow the
        default, which `_ensure_default_model_still_allowed` protects separately.
        """
        stranded = [
            (name, model)
            for name, model in self.agent_repository.list_pinned_models(organization_id)
            if not is_model_allowed(model, allowed_models)
        ]
        if not stranded:
            return

        names = [name for name, _ in stranded]
        models = [
            f"'{model.removeprefix(_OPENROUTER_MODEL_PREFIX)}'" for model in sorted({model for _, model in stranded})
        ]
        subject = "Agent is" if len(names) == 1 else "Agents are"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{len(names)} {subject} still pinned to {_and_list(models)}: {_and_list(names)}. "
                "Point them at an allowed model, or set them to use the organization default, "
                "before removing it from the allowed model list."
            ),
        )

    def create_organization_for_current_user(
        self,
        data: OrganizationCreate,
        actor: CurrentUserContext,
    ) -> OrganizationRead:
        config = get_config()
        allowed_models = [config.agent_default_model.removeprefix("litellm/openrouter/")]

        organization = Organization(
            name=data.name,
            description=data.description,
            created_by_user_id=actor.user.id,
            allowed_models=allowed_models,
        )
        try:
            # Organization creation and the creator's Owner Membership are one
            # transaction, including the concurrency-safe quota check.
            self.organization_repository.create_for_user(
                organization,
                actor.user.id,
                config.organization_creation_limit,
            )
        except OrganizationCreationLimitReached as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"You can create up to {error.limit} organizations",
            ) from error

        if config.litellm_base_url and config.litellm_secret_name:
            try:
                self.litellm.ensure_team_exists(str(organization.id))
            except Exception as exc:
                # Creation already committed; key generation retries provisioning
                # and refuses to issue a key without its team.
                logger.error(
                    "LiteLLM team provisioning deferred for Organization %s (%s)", organization.id, type(exc).__name__
                )
        organization_read = self.organization_repository.get_read(organization.id)
        if not organization_read:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to load organization",
            )
        return organization_read

    def get_paginated_organizations(
        self,
        context: CurrentUserContext,
        org_filter: OrganizationFilter = OrganizationFilter(),
        page: int = 1,
        page_size: int = 15,
    ) -> PaginatedItems[PlatformOrganizationRead]:
        pagination = Pagination(page=page, size=page_size)
        return self.organization_repository.find_all_paginated_platform_read(
            pagination=pagination,
            organization_filter=org_filter,
        )

    def _ensure_can_view_organization(
        self,
        organization_id: UUID,
        context: CurrentUserContext,
    ) -> None:
        self.permission_policy.require_organization(
            context,
            organization_id,
            PermissionKey.ORGANIZATION_READ,
            detail="You don't have permission for this organization",
        )

    def _ensure_is_owner(
        self,
        organization_id: UUID,
        context: CurrentUserContext,
    ) -> None:
        self.permission_policy.require_organization(
            context,
            organization_id,
            PermissionKey.ORGANIZATION_DELETE,
            detail="You don't have permission for this organization",
        )
        context.require_org_role(
            organization_id,
            ORG_OWNER_ONLY_ROLES,
            detail="You don't have permission for this organization",
        )

    def update_organization(
        self,
        organization_id: UUID,
        organization_data: OrganizationUpdate,
        context: CurrentUserContext,
    ) -> OrganizationRead:
        self.permission_policy.require_organization(
            context,
            organization_id,
            PermissionKey.ORGANIZATION_UPDATE,
            detail="You don't have permission for this organization",
        )
        organization = self.organization_repository.get(organization_id)
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )

        dump = organization_data.model_dump(exclude_unset=True)
        delivery_ids: list[UUID] = []

        # Mutate and commit inside a single live session
        # so SQLAlchemy properly tracks list mutations and flushes the UPDATE.
        with Session(self.organization_repository.delegate.engine, expire_on_commit=False) as session:
            session.add(organization)

            from sqlalchemy.orm.attributes import flag_modified

            added_models: list[str] = []
            removed_models: list[str] = []
            allowlist_changed = False
            if "allowed_models" in dump:
                if dump["allowed_models"] is None:
                    # An explicit null is a no-op: allowed_models is non-nullable at
                    # the model level, so never overwrite the stored list with NULL.
                    del dump["allowed_models"]
                else:
                    self._validate_allowed_models(dump["allowed_models"], existing=organization.allowed_models)
                    dump["allowed_models"] = [m.removeprefix("litellm/openrouter/") for m in dump["allowed_models"]]
                    self._ensure_default_model_still_allowed(organization_id, dump["allowed_models"])
                    self._ensure_no_agent_is_pinned_to_a_removed_model(organization_id, dump["allowed_models"])
                    previous_set = set(organization.allowed_models)
                    new_set = set(dump["allowed_models"])
                    added_models = sorted(new_set - previous_set)
                    removed_models = sorted(previous_set - new_set)
                    allowlist_changed = bool(added_models or removed_models)
                    flag_modified(organization, "allowed_models")

            for key, value in dump.items():
                setattr(organization, key, value)
            session.flush()

            if allowlist_changed:
                actor = resolve_actor_identity(context, organization_id)
                event = EVENT_REGISTRY.build_event(
                    event_name=ORGANIZATION_MODEL_ALLOWLIST_CHANGED,
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
                        "added": added_models,
                        "removed": removed_models,
                        "actor_display": context.user.full_name or context.user.email,
                        "subject_display": organization.name,
                    },
                )
                self.organization_repository.outbox_repository.stage(
                    session=session, registry=EVENT_REGISTRY, event=event
                )
                delivery_ids = list(
                    session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id))
                )

            session.commit()

        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)

        organization_read = self.organization_repository.get_read(organization_id)
        if not organization_read:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to load organization",
            )
        return organization_read

    def delete_organization(
        self,
        organization_id: UUID,
        context: CurrentUserContext,
    ) -> None:
        # Deleting an org cascades its agents/templates/skills and orphans running
        # pods, so it is owner/platform-admin only — admins can rename but not destroy.
        self._ensure_is_owner(organization_id, context)
        organization = self.organization_repository.get(organization_id)
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )
        # Deleting an org would cascade its agents and orphan their running pods.
        # Require an explicit teardown: the agents must be deleted first.
        active_agents = self.agent_service.count_active_agents(organization_id)
        if active_agents > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Delete this organization's agents before deleting it ({active_agents} still active)."),
            )
        self.organization_repository.delete(organization.id)
