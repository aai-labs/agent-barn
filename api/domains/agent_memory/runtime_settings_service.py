import hmac
from dataclasses import dataclass
from uuid import UUID

from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from injector import inject, singleton

from api.core.config import Config
from api.domains.agent_memory.key_repository import MemoryKeyRepository
from api.domains.agent_memory.platform_repository import PlatformMemoryRepository
from api.domains.organizations.llm_budget_service import OrganizationLlmBudgetService
from api.domains.organizations.repository import OrganizationRepository
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError


@inject
@singleton
@dataclass
class MemoryRuntimeSettingsService:
    config: Config
    settings: PlatformMemoryRepository
    keys: MemoryKeyRepository
    organizations: OrganizationRepository
    budgets: OrganizationLlmBudgetService
    litellm: LiteLLMClient

    def read(self, authorization: str | None, bank: str | None) -> dict[str, str]:
        scheme, _, token = (authorization or "").partition(" ")
        if (
            scheme.lower() != "bearer"
            or not self.config.memory_runtime_service_key
            or not hmac.compare_digest(token.encode(), self.config.memory_runtime_service_key.encode())
        ):
            raise HTTPException(401, "Invalid memory service credential.")
        model = self.settings.read(self.config.memory_default_model).model
        if bank is None:
            return {"model": model}  # Startup verification has no Organization.
        try:
            organization_id = UUID(bank.removeprefix("org-"))
            if bank != f"org-{organization_id}":
                raise ValueError()
        except ValueError:
            raise HTTPException(422, "Invalid Organization memory bank.") from None
        organization = self.organizations.get(organization_id)
        if organization is None:
            raise HTTPException(404, "Organization not found.")
        if not self.config.agent_token_encryption_key:
            raise HTTPException(503, "Memory processing credentials are unavailable.")

        def create() -> str:
            self.budgets.ensure_memory_team(organization)
            return self.litellm.generate_memory_key(str(organization_id))

        try:
            key = self.keys.resolve(organization_id, self.config.agent_token_encryption_key, create)
        except LiteLLMError, ValueError, InvalidToken:
            raise HTTPException(503, "Memory processing credentials are unavailable.") from None
        return {"model": model, "api_key": key}
