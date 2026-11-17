from dataclasses import dataclass

from injector import inject, singleton

from api.core.config import Config
from api.domains.llm_providers.models import OPENROUTER_SLUG
from api.domains.llm_providers.repository import LlmProviderRepository
from api.infrastructure.crypto import decrypt_token


@inject
@singleton
@dataclass
class OpenRouterKeyLookup:
    repository: LlmProviderRepository
    config: Config

    def api_key(self) -> str:
        """The stored OpenRouter key, else the one in the environment, else empty."""
        found = self.repository.find_active(OPENROUTER_SLUG)
        if found is not None and found[0].api_key_encrypted is not None:
            return decrypt_token(found[0].api_key_encrypted, self.config.agent_token_encryption_key)
        return self.config.openrouter_api_key
