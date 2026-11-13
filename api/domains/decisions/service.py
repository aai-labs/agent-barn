"""Decisions: typed questions that platform features ask a decision model about an Agent.

A feature asks through `DecisionService.decide` with the question types from
`api.infrastructure.litellm.decisions` and gets typed answers back. Which model answers
is a setting, not code: Platform Administrators choose the default by name, a caller
may name another for one call, and `DECISION_MODELS` maps each name to its slug.

The state goes to the model provider exactly as given; what it contains is the caller's choice.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.llm_budget import AgentLlmBudgetService
from api.domains.auth.models import CurrentUserContext
from api.domains.decisions.models import PlatformDecisionSettingsRead, PlatformDecisionSettingsUpdate
from api.domains.decisions.repository import PlatformDecisionRepository
from api.domains.events import EventDeliveryDispatcher
from api.domains.platform_admin.service import PlatformAdminService
from api.infrastructure.litellm.decisions import (
    DecisionError,
    DecisionFailure,
    DecisionResult,
    LiteLLMDecisionClient,
    Question,
)

logger = logging.getLogger(__name__)


@inject
@singleton
@dataclass
class DecisionService:
    """Asks decision models on behalf of platform features.

    Every call is billed to the Agent's own LiteLLM key, as Playbook Extraction is, so
    it lands in the Agent's spend and counts against its limits.
    """

    repository: PlatformDecisionRepository
    authority: PlatformAdminService
    agent_keys: AgentLlmBudgetService
    client: LiteLLMDecisionClient
    config: Config
    dispatcher: EventDeliveryDispatcher

    def decide(
        self,
        agent_id: UUID,
        state: str | Mapping[str, object] | Sequence[object],
        questions: Mapping[str, Question],
        *,
        model: str | None = None,
    ) -> DecisionResult:
        """Ask every question about `state`, billed to the Agent.

        `model` names an entry of DECISION_MODELS for this call only; an unknown name is
        a ValueError. Failures raise DecisionError and never carry request content.
        """
        if model is not None and model not in self.config.decision_models:
            raise ValueError(f"Unknown decision model: {model}")
        slug = self.config.decision_models[model or self.current_model()]
        if not self.config.litellm_base_url:
            raise DecisionError(DecisionFailure.UNAVAILABLE)
        api_key = self.agent_keys.agent_key(agent_id)
        if api_key is None:
            raise DecisionError(DecisionFailure.KEY_OR_MODEL_REJECTED)
        return self.client.decide(api_key, slug, state, questions)

    def current_model(self) -> str:
        """The Platform's chosen name, or the deployment default if that is no longer configured."""
        return self._effective_settings().model

    def read_settings(self, context: CurrentUserContext) -> PlatformDecisionSettingsRead:
        """The model that answers now, which is the default when the saved choice is no longer configured."""
        self.authority.require_platform_admin(context.user)
        return self._effective_settings()

    def _effective_settings(self) -> PlatformDecisionSettingsRead:
        settings = self.repository.read(self.config.decision_default_model)
        if settings.model in self.config.decision_models:
            return settings
        logger.warning("The chosen decision model is no longer configured; using the deployment default")
        return PlatformDecisionSettingsRead(model=self.config.decision_default_model)

    def models(self, context: CurrentUserContext) -> list[dict[str, str]]:
        self.authority.require_platform_admin(context.user)
        return [
            {"value": name, "label": f"{name} ({slug.removeprefix('openrouter/')})"}
            for name, slug in self.config.decision_models.items()
        ]

    def update_settings(
        self, data: PlatformDecisionSettingsUpdate, context: CurrentUserContext
    ) -> PlatformDecisionSettingsRead:
        self.authority.require_platform_admin(context.user)
        if data.model not in self.config.decision_models:
            raise HTTPException(422, "Choose one of the available decision models.")
        result, ids = self.repository.set_model(
            data.model,
            self.config.decision_default_model,
            context.user.id,
            context.user.full_name or context.user.email,
        )
        self.dispatcher.enqueue_immediate(ids)
        return result
