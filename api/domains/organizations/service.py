import fnmatch
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlmodel import Session

from api.core.config import get_config
from api.domains.agent_memory.key_repository import MemoryKeyRepository
from api.domains.agent_settings.lookup import AgentSettingsLookupService
from api.domains.agents.repository import AgentRepository
from api.domains.agents.selection import _OPENROUTER_MODEL_PREFIX, is_model_allowed
from api.domains.agents.service import AgentService
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
    ORGANIZATION_MODEL_ALLOWLIST_CHANGED,
    ORGANIZATION_UPDATED,
)
from api.domains.onboarding.settings_service import TrialSettingsService
from api.domains.organizations.exceptions import OrganizationCreationLimitReached
from api.domains.organizations.llm_budget_service import OrganizationLlmBudgetService
from api.domains.organizations.lookup import OrganizationAgentLimit
from api.domains.organizations.models import (
    CreditGrantKind,
    Organization,
    OrganizationCreate,
    OrganizationFilter,
    OrganizationRead,
    OrganizationTrialEnd,
    OrganizationUpdate,
    PlatformOrganizationRead,
)
from api.domains.organizations.repository import OrganizationRepository
from api.domains.organizations.settings_service import OrganizationSettingsService
from api.domains.rbac.catalog import ORG_OWNER_ONLY_ROLES, PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.litellm.client import ONE_OFF_BUDGET_WINDOW
from api.infrastructure.shared.models import PaginatedItems, Pagination

logger = logging.getLogger(__name__)

_TRACKED_ORGANIZATION_FIELDS = ("name", "description")


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
    llm_budgets: OrganizationLlmBudgetService
    agent_service: AgentService
    permission_policy: PermissionPolicy
    event_delivery_dispatcher: EventDeliveryDispatcher
    agent_settings_lookup: AgentSettingsLookupService
    agent_repository: AgentRepository
    memory_keys: MemoryKeyRepository
    trial_settings: TrialSettingsService
    organization_settings: OrganizationSettingsService

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
        # The read carries the Organization's own limit; members see the one in force.
        organization.agent_limit = self._agent_limit_in_force(organization.agent_limit, organization.is_trial)
        if organization.agent_limit is not None:
            organization.agent_limit_reached = (
                self.agent_repository.count_active_by_org(organization_id) >= organization.agent_limit
            )
            if organization.is_trial:
                organization.trial_agent_limit = organization.agent_limit
                organization.trial_agent_limit_reached = organization.agent_limit_reached
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
        organization.agent_limit_in_force = self._agent_limit_in_force(organization.agent_limit, organization.is_trial)
        return organization

    def _agent_limit_in_force(self, own: int | None, is_trial: bool) -> int | None:
        return OrganizationAgentLimit(own=own, is_trial=is_trial).in_force(
            trial_limit=self.trial_settings.agent_limit, default=self.organization_settings.default_agent_limit
        )

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
        still_on_trial = actor.user.signed_up_at is not None and actor.user.trial_ended_at is None
        if still_on_trial or self.organization_repository.owns_active_trial(actor.user.id):
            # Another Organization would be spend outside the trial's limits, including
            # after deleting the trial. Once the trial ends (a purchase, or a Platform
            # Administrator), its owner creates Organizations that run on credit.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Trial accounts can't create more organizations.",
            )
        config = get_config()
        allowed_models = [config.agent_default_model.removeprefix("litellm/openrouter/")]

        organization = Organization(
            name=data.name,
            description=data.description,
            created_by_user_id=actor.user.id,
            allowed_models=allowed_models,
        )
        # With self-signup on, only accounts a Platform Administrator set up spend the
        # platform's budget. Everyone else (signed up themselves, or invited by an
        # Organization, which a trial's owner can do with an address of their own) pays
        # for what their Organizations spend: each runs on credit, starting with none.
        # Without self-signup every account traces back to a Platform Administrator or an
        # Organization they set up, so there is nothing to close.
        policy = self.trial_settings.signup_policy()
        on_credit = policy.self_signup_enabled and not (
            actor.user.is_platform_admin or actor.user.platform_provisioned_at is not None
        )
        # Their first Organization of their own is a trial when their address has never
        # had one: an invited member gets the trial they'd have had by signing up. Someone
        # who signed themselves up has had theirs, whatever the record says.
        email = actor.user.email
        trial = on_credit and actor.user.signed_up_at is None and not self._has_had_trial(email)
        opening_credit = Decimal(0)
        if on_credit:
            if trial:
                opening_credit = Decimal(str(policy.credit_usd))
                organization.is_trial = True
            organization.llm_budget_usd = float(opening_credit)
            organization.llm_budget_duration = ONE_OFF_BUDGET_WINDOW

        def admit_trial(session: Session) -> None:
            # Under the lock sign-up takes too, so two trials can't take the last place.
            if self.trial_settings.trials_full(session):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="No free trials are available right now. Try again later.",
                )
            # Looked up before the lock: a sign-up with the same inbox, or this request
            # sent twice, may have taken the address's trial since. Trying again
            # creates the Organization on credit.
            if self.trial_settings.has_had_trial(email, session):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Your organization couldn't be created. Try again.",
                )
            self.trial_settings.record_trial(email, session)

        try:
            # Organization creation and the creator's Owner Membership are one
            # transaction, including the concurrency-safe quota check.
            organization, delivery_ids = self.organization_repository.create_for_user(
                organization,
                actor.user.id,
                config.organization_creation_limit,
                ActorIdentity(type=ActorIdentityType.USER, id=actor.user.id),
                opening_credit_usd=opening_credit if on_credit else None,
                opening_credit_kind=CreditGrantKind.TRIAL if trial else CreditGrantKind.ADJUSTMENT,
                in_transaction=admit_trial if trial else None,
            )
        except OrganizationCreationLimitReached as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"You can create up to {error.limit} organizations",
            ) from error
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)

        # With its limit already on it: a new Organization is capped from the start.
        # Best effort — creation is committed, and key generation provisions again.
        self.llm_budgets.provision_team(organization.id)
        organization_read = self.organization_repository.get_read(organization.id)
        if not organization_read:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to load organization",
            )
        return organization_read

    def _has_had_trial(self, email: str) -> bool:
        with Session(self.organization_repository.delegate.engine) as session:
            return self.trial_settings.has_had_trial(email, session)

    def set_agent_limit(
        self, organization_id: UUID, agent_limit: int | None, context: CurrentUserContext
    ) -> PlatformOrganizationRead:
        """Set how many Agents an Organization may run; None returns it to the default.
        Agents already running are kept: a lower limit only stops new hires."""
        context.require_platform_admin()
        result = self.organization_repository.set_agent_limit_with_event(
            organization_id,
            agent_limit,
            actor=resolve_actor_identity(context, organization_id),
            actor_display=context.user.full_name or context.user.email,
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization {organization_id} not found"
            )
        self.event_delivery_dispatcher.enqueue_immediate(result[1])
        return self.get_platform_organization(organization_id)

    def convert_trial(self, organization_id: UUID, *, actor: ActorIdentity, actor_display: str) -> bool:
        """Make a trial an ordinary Organization because it bought credit.

        System-initiated, so no permission check. Unlike a Platform Administrator ending
        it, the Organization stays on credit: its ledger and ceiling are untouched, and
        an expired trial is expired no longer. False when it was not a trial.
        """
        organization = self.organization_repository.get(organization_id)
        if organization is None or not organization.is_trial:
            return False
        result = self.organization_repository.end_trial_with_event(
            organization_id, actor=actor, actor_display=actor_display
        )
        if result is None:
            return False
        self.event_delivery_dispatcher.enqueue_immediate(result[1])
        return True

    def end_trial(
        self, organization_id: UUID, data: OrganizationTrialEnd, context: CurrentUserContext
    ) -> PlatformOrganizationRead:
        """Make a trial an ordinary Organization on the spend limit the administrator chose.

        The limit is stored through the ordinary spend-limit path. If the proxy cannot
        take it yet, the limit is still saved for the reconciler, so the trial ends anyway
        and the administrator gets the usual "saved, not applied yet" answer: a trial is
        never left half-ended on a renewing budget.
        """
        context.require_platform_admin()
        organization = self.organization_repository.get(organization_id)
        if organization is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization {organization_id} not found"
            )
        if not organization.is_trial:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This organization isn't on a trial.")
        not_yet_applied: HTTPException | None = None
        try:
            self.llm_budgets.set_llm_budget(organization_id, data.budget_usd, data.budget_duration, context)
        except HTTPException as exc:
            if exc.status_code != status.HTTP_502_BAD_GATEWAY:
                raise
            not_yet_applied = exc
        result = self.organization_repository.end_trial_with_event(
            organization_id,
            actor=resolve_actor_identity(context, organization_id),
            actor_display=context.user.full_name or context.user.email,
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization {organization_id} not found"
            )
        self.event_delivery_dispatcher.enqueue_immediate(result[1])
        if not_yet_applied is not None:
            raise not_yet_applied
        organization_read = self.organization_repository.get_platform_read(organization_id)
        if organization_read is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization {organization_id} not found"
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

            changed_fields = sorted(
                key for key in _TRACKED_ORGANIZATION_FIELDS if key in dump and dump[key] != getattr(organization, key)
            )
            for key, value in dump.items():
                setattr(organization, key, value)
            session.flush()
            actor = resolve_actor_identity(context, organization_id)

            if allowlist_changed:
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
                delivery_ids += self.organization_repository.outbox_repository.delivery_ids_for_event(
                    session, event.event_id
                )
            if changed_fields:
                updated = EVENT_REGISTRY.build_event(
                    event_name=ORGANIZATION_UPDATED,
                    schema_version=1,
                    occurred_at=datetime.now(UTC),
                    organization_id=organization_id,
                    actor=ActorIdentity(type=ActorIdentityType.USER, id=context.user.id),
                    subject=SubjectIdentity(
                        type=SubjectIdentityType.ORGANIZATION,
                        id=organization_id,
                        organization_id=organization_id,
                    ),
                    correlation_id=uuid4(),
                    payload={"organization_id": organization_id, "changed_fields": changed_fields},
                )
                self.organization_repository.outbox_repository.stage(
                    session=session, registry=EVENT_REGISTRY, event=updated
                )
                delivery_ids += self.organization_repository.outbox_repository.delivery_ids_for_event(
                    session, updated.event_id
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
        delivery_ids = self.organization_repository.delete_with_event(
            organization.id,
            ActorIdentity(type=ActorIdentityType.USER, id=context.user.id),
            before_delete=lambda session: self.memory_keys.enqueue_deletion(organization.id, session),
        )
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
        try:
            self.memory_keys.revoke_pending(self.llm_budgets.litellm.revoke_memory_key, organization_id=organization.id)
        except Exception as exc:
            # The durable cleanup intent already committed with deletion.
            logger.warning("Memory credential cleanup deferred: %s", type(exc).__name__)
