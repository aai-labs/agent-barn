"""An Agent's own model spend limit: resolving it, setting it, keeping its key in step,
and noticing when it runs out.

The limit is enforced by LiteLLM on the Agent's own key, alongside its Organization's
team budget. The row is authoritative; the key mirrors it.

A leaf service on purpose. It depends only on the agent repository, the proxy and
two lookups, so AgentService (for a new Agent's key) and the Organization's budget
service (for the consequences of an Organization limit) can both inject it without
an import cycle.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlmodel import Session

from api.core.config import Config
from api.domains.agent_settings.lookup import AgentSettingsLookupService
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import (
    Agent,
    AgentLlmBudgetListItem,
    AgentLlmBudgetRead,
    AgentLlmBudgetSource,
    AgentLlmBudgetState,
)
from api.domains.agents.repository import AgentRepository
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
    AGENT_LLM_BUDGET_EXHAUSTED,
    AGENT_LLM_BUDGET_THRESHOLD_REACHED,
    EVENT_REGISTRY,
)
from api.domains.organizations.lookup import OrganizationLlmLimit, OrganizationLookupService
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.litellm.client import LiteLLMClient

logger = logging.getLogger(__name__)

# Written into the audit record when an Agent's limit moves because its
# Organization's did, not because anyone asked for it.
LOWERED_TO_FIT_ORGANIZATION = "Lowered to fit within the organization's spend limit."

_SYSTEM_ACTOR = ActorIdentity(type=ActorIdentityType.SYSTEM, id="llm-budget")


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class ResolvedAgentLimit:
    limit_usd: float
    source: AgentLlmBudgetSource


def resolve_agent_limit(
    own_usd: float | None, default_usd: float, organization: OrganizationLlmLimit
) -> ResolvedAgentLimit:
    """The limit an Agent's key carries: its own, else the default, never above its
    Organization's. The last rule is what keeps a platform-wide default that exceeds
    one Organization's own limit from putting that Organization's Agents over it."""
    wanted, source = (own_usd, "agent") if own_usd is not None else (default_usd, "default")
    if wanted > organization.limit_usd:
        return ResolvedAgentLimit(organization.limit_usd, "organization")
    return ResolvedAgentLimit(wanted, source)


@dataclass(frozen=True)
class AgentKeyBudget:
    """The policy a brand-new Agent key starts with, and its team's."""

    agent_limit_usd: float
    organization_limit_usd: float
    window: str


@dataclass(frozen=True)
class AgentBudgetCrossing:
    agent: Agent
    threshold_percent: int
    spend_usd: float
    limit_usd: float
    renews_at: str | None


@inject
@singleton
@dataclass
class AgentLlmBudgetService:
    repository: AgentRepository
    authorization: AgentAuthorization
    permission_policy: PermissionPolicy
    litellm: LiteLLMClient
    organization_lookup: OrganizationLookupService
    agent_settings_lookup: AgentSettingsLookupService
    event_delivery_dispatcher: EventDeliveryDispatcher
    config: Config

    def _litellm_configured(self) -> bool:
        return bool(self.config.litellm_base_url and self.config.litellm_secret_name)

    def _organization_limit(self, organization_id: UUID) -> OrganizationLlmLimit:
        limit = self.organization_lookup.get_llm_limit(organization_id)
        if limit is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
        return limit

    # --- a new Agent ---------------------------------------------------------------

    def key_budget_for_new_agent(self, organization_id: UUID) -> AgentKeyBudget:
        """A new Agent inherits the default, so its key starts at the default held
        beneath its Organization's limit — capped from its very first call."""
        organization = self._organization_limit(organization_id)
        resolved = resolve_agent_limit(
            None, self.agent_settings_lookup.resolve_default_agent_llm_budget(organization_id), organization
        )
        return AgentKeyBudget(
            agent_limit_usd=resolved.limit_usd,
            organization_limit_usd=organization.limit_usd,
            window=organization.window,
        )

    # --- one Agent, on request -----------------------------------------------------

    def get_llm_budget(self, agent_id: UUID, context: CurrentUserContext) -> AgentLlmBudgetRead:
        agent = self.authorization.require_action(
            context,
            agent_id,
            PermissionKey.COST_READ,
            detail="You don't have permission to view this agent's costs.",
        )
        return self._read(agent, context)

    def set_llm_budget(
        self, agent_id: UUID, amount_usd: float | None, context: CurrentUserContext
    ) -> AgentLlmBudgetRead:
        """Store an Agent's own limit and mirror it onto its key.

        Refused rather than clamped above the Organization's limit: silently storing
        less than was asked for would leave the caller believing a number that is not
        in force. The sum of Agent limits may exceed the Organization's — the team
        budget still binds, and forbidding it would make every change a puzzle.
        """
        agent = self.authorization.require_visible(context, agent_id)
        self.permission_policy.require(
            context,
            agent.organization_id,
            PermissionKey.LLM_BUDGET_MANAGE,
            detail="You don't have permission to change this agent's spend limit.",
        )
        organization = self._organization_limit(agent.organization_id)
        if amount_usd is not None and amount_usd > organization.limit_usd:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                # No straight apostrophes: settings surfaces render a single-quoted
                # run of an error detail as a code identifier.
                detail=(
                    "The spend limit for an agent cannot be more than the organization limit "
                    f"(${organization.limit_usd:,.2f})."
                ),
            )
        if amount_usd == agent.llm_budget_usd:
            # No transition, so no Event: an audit trail of unchanged values is noise.
            return self._read(agent, context)

        result = self.repository.set_llm_budget_with_event(
            agent.id,
            amount_usd,
            actor=resolve_actor_identity(context, agent.organization_id),
            actor_display=context.user.full_name or context.user.email,
        )
        if result is None:
            # Deleted between the visibility check and the write.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        updated, delivery_ids = result
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
        if not self._push_key(updated, organization):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Spend limit saved, but it could not be applied yet. It will be retried automatically.",
            )
        return self._read(updated, context)

    def list_llm_budgets(self, organization_id: UUID, context: CurrentUserContext) -> list[AgentLlmBudgetListItem]:
        """Every live Agent's limit in force and where it comes from, for the
        Organization's spend-limit overview.

        Organization-wide `cost.read`, the audience of the Organization's other spend
        figures, which already sees every Agent through implicit Owner authority.
        """
        self.permission_policy.require(
            context,
            organization_id,
            PermissionKey.COST_READ,
            detail="You don't have permission to view organization costs.",
        )
        organization = self._organization_limit(organization_id)
        default = self.agent_settings_lookup.resolve_default_agent_llm_budget(organization_id)
        rows = []
        for agent in self.repository.list_llm_budget_targets(organization_id, with_key=False):
            resolved = resolve_agent_limit(agent.llm_budget_usd, default, organization)
            observed = agent.llm_spend_observed_at is not None
            rows.append(
                AgentLlmBudgetListItem(
                    agent_id=agent.id,
                    agent_name=agent.name,
                    limit_usd=resolved.limit_usd,
                    own_limit_usd=agent.llm_budget_usd,
                    source=resolved.source,
                    state=self._state(agent, resolved.limit_usd),
                    spend_usd=agent.llm_spend_usd if observed else None,
                )
            )
        return sorted(rows, key=lambda row: row.agent_name.lower())

    def _read(self, agent: Agent, context: CurrentUserContext) -> AgentLlmBudgetRead:
        organization = self._organization_limit(agent.organization_id)
        default = self.agent_settings_lookup.resolve_default_agent_llm_budget(agent.organization_id)
        resolved = resolve_agent_limit(agent.llm_budget_usd, default, organization)
        return AgentLlmBudgetRead(
            limit_usd=resolved.limit_usd,
            own_limit_usd=agent.llm_budget_usd,
            source=resolved.source,
            default_limit_usd=min(default, organization.limit_usd),
            organization_limit_usd=organization.limit_usd,
            window=organization.window,
            state=self._state(agent, resolved.limit_usd),
            spend_usd=agent.llm_spend_usd if agent.llm_spend_observed_at is not None else None,
            # An Agent key renews with its Organization's team, so the Organization's
            # date — known as soon as a limit is written — stands in until this key's
            # own snapshot has been taken.
            renews_at=agent.llm_budget_renews_at or organization.renews_at,
            can_manage=self.permission_policy.resolve(context, agent.organization_id, PermissionKey.LLM_BUDGET_MANAGE)
            is not None,
        )

    def _state(self, agent: Agent, limit: float) -> AgentLlmBudgetState:
        spend = agent.llm_spend_usd
        if spend is None or agent.llm_spend_observed_at is None:
            return AgentLlmBudgetState.UNKNOWN
        if spend >= limit:
            return AgentLlmBudgetState.EXHAUSTED
        if limit > 0 and spend >= limit * min(self.config.llm_budget_alert_thresholds) / 100:
            return AgentLlmBudgetState.WARNING
        return AgentLlmBudgetState.OK

    # --- every Agent in an Organization, after its limits moved -------------------

    def llm_credentials(self, organization_id: UUID) -> list[tuple[UUID, str, str]]:
        """(agent id, name, encrypted key) for the Organization's live Agents — for
        the platform's coverage census."""
        return self.repository.list_llm_credentials(organization_id)

    def count_by_source(self, organization_id: UUID) -> tuple[int, int]:
        """(inheriting, own) — for the default Agent limit's reach."""
        return self.repository.count_by_llm_budget_source(organization_id)

    def key_limits(self, organization_id: UUID) -> dict[UUID, float]:
        """Each Agent key's resolved limit right now. Taken before an Organization-wide
        change so that afterwards only the keys whose limit actually moved are
        rewritten — every other one would cost a proxy round trip for nothing."""
        organization = self._organization_limit(organization_id)
        default = self.agent_settings_lookup.resolve_default_agent_llm_budget(organization_id)
        return {
            agent.id: resolve_agent_limit(agent.llm_budget_usd, default, organization).limit_usd
            for agent in self.repository.list_llm_budget_targets(organization_id)
        }

    def fit_to_organization(
        self,
        organization_id: UUID,
        *,
        before: dict[UUID, float] | None,
        actor: ActorIdentity,
        actor_display: str,
    ) -> int:
        """Bring every Agent within its Organization's current limit and default.

        Agent limits above the Organization's are pulled down to it, each with an
        audit record saying why; then every key whose resolved limit differs from
        `before` is rewritten (all of them when `before` is None). Returns the number
        of keys that could not be updated, which the scheduled reconciliation
        retries — the rows are already right.
        """
        organization = self._organization_limit(organization_id)
        _, delivery_ids = self.repository.lower_llm_budgets_above(
            organization_id,
            organization.limit_usd,
            actor=actor,
            actor_display=actor_display,
            reason=LOWERED_TO_FIT_ORGANIZATION,
        )
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
        if not self._litellm_configured():
            return 0
        default = self.agent_settings_lookup.resolve_default_agent_llm_budget(organization_id)
        failures = 0
        for agent in self.repository.list_llm_budget_targets(organization_id):
            limit = resolve_agent_limit(agent.llm_budget_usd, default, organization).limit_usd
            if before is not None and before.get(agent.id) == limit:
                continue
            failures += 0 if self._push_key(agent, organization) else 1
        return failures

    def _push_key(self, agent: Agent, organization: OrganizationLlmLimit) -> bool:
        if not self._litellm_configured() or not agent.litellm_key_encrypted:
            return True
        default = self.agent_settings_lookup.resolve_default_agent_llm_budget(agent.organization_id)
        limit = resolve_agent_limit(agent.llm_budget_usd, default, organization).limit_usd
        try:
            key = decrypt_token(agent.litellm_key_encrypted, self.config.agent_token_encryption_key)
            self.litellm.apply_key_budget(key, limit, organization.window)
        except Exception:
            # Deliberately broad, and never logs the key: the Kubernetes read behind
            # the master key fails with its own error types, and a key that cannot be
            # decrypted must not end the sweep either.
            logger.warning("Could not apply the spend limit to Agent %s's key", agent.id)
            return False
        return True

    # --- scheduled -------------------------------------------------------------------

    def reconcile_key_budgets(self) -> None:
        """Repair drift between stored Agent limits and their keys.

        Also re-applies the "never above the Organization" rule, so an Agent limit left
        above a lowered Organization limit by an interrupted request is brought back
        within it. Best effort by design, like the team reconciliation.
        """
        if not self._litellm_configured():
            return
        organization_ids = {agent.organization_id for agent in self.repository.list_llm_budget_targets()}
        failures = 0
        for organization_id in organization_ids:
            try:
                failures += self.fit_to_organization(
                    organization_id, before=None, actor=_SYSTEM_ACTOR, actor_display="Spend limit reconciliation"
                )
            except Exception:
                failures += 1
                logger.exception("Agent spend limit reconciliation failed for Organization %s", organization_id)
        if failures:
            logger.error("Agent spend limit reconciliation: %s key(s) could not be updated", failures)

    def check_llm_budget_thresholds(self) -> list[AgentBudgetCrossing]:
        """Refresh each Agent's spend snapshot and report new threshold crossings.

        Informational only: the proxy enforces the limit in the request path.
        """
        if not self._litellm_configured():
            return []
        fired: list[AgentBudgetCrossing] = []
        limits: dict[UUID, OrganizationLlmLimit | None] = {}
        for agent in self.repository.list_llm_budget_targets():
            if agent.organization_id not in limits:
                limits[agent.organization_id] = self.organization_lookup.get_llm_limit(agent.organization_id)
            organization = limits[agent.organization_id]
            if organization is None:
                continue
            try:
                crossing = self._check_one(agent, organization)
            except Exception:
                logger.exception("Agent spend limit check failed for Agent %s", agent.id)
                continue
            # Recorded only once the notification is staged; the other order loses an
            # alert whose publish failed instead of delaying it.
            if crossing is None or not self._publish_crossing(crossing):
                continue
            agent.llm_alerted_threshold = crossing.threshold_percent
            self.repository.save(agent)
            fired.append(crossing)
        if fired:
            logger.info("Agent spend limit thresholds crossed: %s", len(fired))
        return fired

    def _check_one(self, agent: Agent, organization: OrganizationLlmLimit) -> AgentBudgetCrossing | None:
        key = decrypt_token(agent.litellm_key_encrypted, self.config.agent_token_encryption_key)
        status_ = self.litellm.get_key_budget_status(key)
        if status_.get("spend") is None:
            # "Could not read it" is not "nothing spent"; keep the previous snapshot.
            return None
        default = self.agent_settings_lookup.resolve_default_agent_llm_budget(agent.organization_id)
        limit = resolve_agent_limit(agent.llm_budget_usd, default, organization).limit_usd
        spend = float(status_["spend"])
        renews_at = status_.get("renews_at")
        agent.llm_spend_usd = spend
        agent.llm_spend_observed_at = datetime.now(UTC)
        agent.llm_budget_renews_at = _parse_timestamp(renews_at)

        # Spans the window and the limit, so a renewal or a limit change re-arms the
        # thresholds instead of leaving the Agent silent for the rest of the period.
        alert_key = f"{renews_at}|{limit}"
        if agent.llm_alert_key != alert_key:
            agent.llm_alert_key = alert_key
            agent.llm_alerted_threshold = None
        self.repository.save(agent)

        thresholds = self.config.llm_budget_alert_thresholds
        reached = [t for t in thresholds if limit > 0 and spend >= limit * t / 100] or ([100] if limit == 0 else [])
        highest = max(reached, default=None)
        already = agent.llm_alerted_threshold
        if highest is None or (already is not None and highest <= already):
            return None
        return AgentBudgetCrossing(
            agent=agent, threshold_percent=highest, spend_usd=spend, limit_usd=limit, renews_at=renews_at
        )

    def _publish_crossing(self, crossing: AgentBudgetCrossing) -> bool:
        agent = crossing.agent
        event_name = (
            AGENT_LLM_BUDGET_EXHAUSTED if crossing.threshold_percent >= 100 else AGENT_LLM_BUDGET_THRESHOLD_REACHED
        )
        try:
            with Session(self.repository.delegate.engine, expire_on_commit=False) as session:
                event = EVENT_REGISTRY.build_event(
                    event_name=event_name,
                    schema_version=1,
                    occurred_at=datetime.now(UTC),
                    organization_id=agent.organization_id,
                    actor=ActorIdentity(type=ActorIdentityType.SYSTEM, id="llm-budget-alerts"),
                    subject=SubjectIdentity(
                        type=SubjectIdentityType.AGENT, id=agent.id, organization_id=agent.organization_id
                    ),
                    correlation_id=uuid4(),
                    payload={
                        "organization_id": agent.organization_id,
                        "agent_id": agent.id,
                        "threshold_percent": crossing.threshold_percent,
                        "spend_usd": crossing.spend_usd,
                        "limit_usd": crossing.limit_usd,
                        "renews_at": crossing.renews_at,
                        "subject_display": agent.name,
                    },
                )
                self.repository.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
                delivery_ids = self.repository.outbox_repository.delivery_ids_for_event(session, event.event_id)
                session.commit()
            self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
        except Exception:
            logger.exception("Failed to publish spend limit alert for Agent %s", agent.id)
            return False
        return True
