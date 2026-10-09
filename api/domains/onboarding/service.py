"""Trial onboarding: setting up a new user's Agent and remembering when they finished.

A self-signed-up user's trial Organization gets one Hermes Agent with an Agent Barn
Telegram Connection, started straight away. Setup runs as the user, through the same
services and authorization as the dashboard, and is safe to repeat: onboarding calls it
whenever it opens, and each call only does what is still missing.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.exceptions import TrialAgentLimitReached
from api.domains.agents.models import AgentCreate, AgentFilter, AgentRead, AgentStatus, AgentType
from api.domains.agents.service import AgentService
from api.domains.auth.models import CurrentUserContext
from api.domains.communications.models import CommunicationConnectionCreate, CommunicationConnectionRead
from api.domains.communications.service import CommunicationsService
from api.domains.onboarding.models import OnboardingRead
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.users.service import UserService
from api.infrastructure.shared.models import Pagination

logger = logging.getLogger(__name__)

TRIAL_TEMPLATE_KEY = "general-purpose"
TELEGRAM_PLATFORM_KEY = "agentbarn_telegram"
# What the hire dialog calls a General Purpose Agent.
_AGENT_ROLE = "the Assistant"
# Not yet started, or failed to: onboarding starts it (again).
_STARTABLE = frozenset({AgentStatus.STOPPED, AgentStatus.ERROR})


@inject
@singleton
@dataclass
class OnboardingService:
    agents: AgentService
    communications: CommunicationsService
    organizations: OrganizationLookupService
    users: UserService
    config: Config

    def _trial_context(self, context: CurrentUserContext) -> CurrentUserContext | None:
        """The caller acting in their own trial, or None when onboarding is not theirs to do:
        they were brought in by someone else, or have already finished."""
        user = context.user
        if user.signed_up_at is None or user.onboarding_completed_at is not None:
            return None
        organization_id = self.organizations.first_created_by(user.id)
        membership = context.user_organization_map.get(organization_id) if organization_id else None
        if membership is None:
            return None
        return context.model_copy(update={"current_user_organization": membership})

    def read(self, context: CurrentUserContext) -> OnboardingRead:
        trial = self._trial_context(context)
        if trial is None:
            return OnboardingRead(required=False, completed_at=context.user.onboarding_completed_at)
        agent = self._agent(trial)
        connection = self._telegram_connection(agent.id, trial) if agent else None
        return self._read(trial, agent, connection)

    def set_up_agent(self, context: CurrentUserContext) -> OnboardingRead:
        trial = self._trial_context(context)
        if trial is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="There is nothing left to set up.")
        agent = self._agent(trial) or self._create_agent(trial)
        # Before starting: the Agent picks up its Connection when it starts.
        try:
            connection, created = self._ensure_telegram_connection(agent.id, trial)
        except HTTPException as exc:
            # Retrying won't help with most of these (no shared bot, for one), so say why.
            logger.warning(
                "Onboarding could not give agent %s its Telegram connection (%s: %s)",
                agent.id,
                exc.status_code,
                exc.detail,
            )
            raise
        if agent.status in _STARTABLE:
            agent = self._start(agent, trial)
        elif created and agent.status == AgentStatus.RUNNING:
            # Already running without it, so it must start again to use the new one.
            agent = self._start(self.agents.stop_agent(agent.id, trial), trial)
        return self._read(trial, agent, connection)

    def _ensure_telegram_connection(
        self, agent_id: UUID, trial: CurrentUserContext
    ) -> tuple[CommunicationConnectionRead, bool]:
        """The Agent's Telegram Connection, and whether this call created it."""
        existing = self._telegram_connection(agent_id, trial)
        if existing is not None:
            return existing, False
        try:
            created = self.communications.create_connection(
                agent_id,
                CommunicationConnectionCreate(
                    platform_key=TELEGRAM_PLATFORM_KEY, display_name="Telegram", enabled=True, credentials={}
                ),
                trial,
            )
            return created, True
        except HTTPException as exc:
            # A concurrent setup created it first; that one is the Connection.
            concurrent = self._telegram_connection(agent_id, trial) if exc.status_code == 409 else None
            if concurrent is None:
                raise
            return concurrent, False

    def _start(self, agent: AgentRead, trial: CurrentUserContext) -> AgentRead:
        try:
            return self.agents.start_agent(agent.id, trial)
        except HTTPException as exc:
            # The failure is recorded on the Agent; onboarding shows it and offers a retry.
            logger.warning("Onboarding could not start agent %s (%s)", agent.id, exc.status_code)
            return self.agents.get_agent(agent.id, trial)

    def complete(self, context: CurrentUserContext) -> None:
        self.users.complete_onboarding(context.user.id)

    def _agent(self, trial: CurrentUserContext) -> AgentRead | None:
        """The trial's oldest live Agent: the one onboarding set up, even after the user
        hires more. Agent lists are oldest first."""
        page = self.agents.list_agents(AgentFilter(), Pagination(page=1, size=1), trial)
        return page.items[0] if page.items else None

    def _create_agent(self, trial: CurrentUserContext) -> AgentRead:
        name = f"{self.agents.suggest_agent_name(trial).first_name} {_AGENT_ROLE}"
        try:
            return self.agents.create_agent(
                AgentCreate(name=name, agent_type=AgentType.HERMES, template_key=TRIAL_TEMPLATE_KEY), trial
            )
        except TrialAgentLimitReached:
            # Another onboarding request created it first.
            agent = self._agent(trial)
            if agent is None:
                raise
            return agent

    def _telegram_connection(self, agent_id: UUID, trial: CurrentUserContext) -> CommunicationConnectionRead | None:
        connections = self.communications.list_connections(agent_id, trial)
        return next((c for c in connections if c.platform_key == TELEGRAM_PLATFORM_KEY), None)

    def _read(
        self,
        trial: CurrentUserContext,
        agent: AgentRead | None,
        connection: CommunicationConnectionRead | None,
    ) -> OnboardingRead:
        organization_id = trial.require_current_user_organization().organization_id
        limit = self.organizations.get_llm_limit(organization_id)
        return OnboardingRead(
            required=True,
            organization_id=organization_id,
            credit_usd=limit.limit_usd if limit else None,
            agent_id=agent.id if agent else None,
            agent_name=agent.name if agent else None,
            agent_status=agent.status.value if agent else None,
            connection_id=connection.id if connection else None,
            telegram_bot_username=self.config.agentbarn_telegram_bot_username or None,
        )
