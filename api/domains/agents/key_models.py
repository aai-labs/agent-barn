from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.agent_settings.lookup import AgentSettingsLookupService
from api.domains.agents.models import Agent
from api.domains.agents.repository import AgentRepository
from api.domains.playbooks.platform_repository import PlatformPlaybookRepository
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.litellm.client import LiteLLMClient


def _runtime_model_name(model: str) -> str:
    _, sep, name = model.partition("/")
    return name if sep else model


def key_models(agent_models: Iterable[str], platform_models: Iterable[str]) -> list[str]:
    names = {_runtime_model_name(model) for model in agent_models} | set(platform_models)
    return sorted(name for name in names if name)


@inject
@singleton
@dataclass
class AgentKeyModelService:
    repository: AgentRepository
    agent_settings_lookup: AgentSettingsLookupService
    playbook_settings: PlatformPlaybookRepository
    litellm: LiteLLMClient
    config: Config

    def _litellm_configured(self) -> bool:
        return bool(self.config.litellm_base_url and self.config.litellm_secret_name)

    def _platform_models(self) -> list[str]:
        return [
            *self.config.decision_models.values(),
            self.playbook_settings.read(self.config.playbook_default_model).model,
        ]

    def models_for(self, agent: Agent, starting_model: str | None = None) -> list[str]:
        next_model = agent.model or self.agent_settings_lookup.resolve_default_model(agent.organization_id)
        return key_models([agent.running_model, next_model, starting_model or ""], self._platform_models())

    def sync(self, agent: Agent, starting_model: str | None = None) -> bool:
        return self._sync(agent.id, starting_model)

    def sync_by_id(self, agent_id: UUID) -> bool:
        return self._sync(agent_id, None)

    def _sync(self, agent_id: UUID, starting_model: str | None) -> bool:
        if not self._litellm_configured():
            return False
        return self.repository.with_key_models_lock(agent_id, lambda agent: self._set(agent, starting_model))

    def _set(self, agent: Agent | None, starting_model: str | None) -> bool:
        if agent is None or not agent.litellm_key_encrypted:
            return False
        key = decrypt_token(agent.litellm_key_encrypted, self.config.agent_token_encryption_key)
        return self.litellm.set_key_models(key, self.models_for(agent, starting_model))
