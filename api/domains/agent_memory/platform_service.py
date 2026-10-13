from dataclasses import dataclass

from fastapi import HTTPException
from injector import inject, singleton

from api.core.config import Config
from api.domains.agent_memory.platform_models import PlatformMemorySettingsRead, PlatformMemorySettingsUpdate
from api.domains.agent_memory.platform_repository import PlatformMemoryRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher
from api.domains.platform_admin.service import PlatformAdminService
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError
from api.infrastructure.openrouter.client import OpenRouterClient, OpenRouterError


@inject
@singleton
@dataclass
class PlatformMemoryService:
    repository: PlatformMemoryRepository
    authority: PlatformAdminService
    catalog: OpenRouterClient
    litellm: LiteLLMClient
    config: Config
    dispatcher: EventDeliveryDispatcher

    def read(self, context: CurrentUserContext) -> PlatformMemorySettingsRead:
        self.authority.require_platform_admin(context.user)
        return self.repository.read(self.config.memory_default_model)

    def models(self, context: CurrentUserContext) -> list[dict[str, str]]:
        self.authority.require_platform_admin(context.user)
        try:
            models = self.catalog.list_models()
        except OpenRouterError:
            raise HTTPException(503, "The model catalog is unavailable.") from None
        # Hindsight needs text, structured responses, and function tools.
        return [
            {"value": f"openrouter/{m['id']}", "label": m["name"]}
            for m in models
            if "text" in m.get("output_modalities", [])
            and "tools" in m.get("supported_parameters", [])
            and {"response_format", "structured_outputs"}.intersection(m.get("supported_parameters", []))
        ]

    def update(self, data: PlatformMemorySettingsUpdate, context: CurrentUserContext) -> PlatformMemorySettingsRead:
        self.authority.require_platform_admin(context.user)
        if data.model not in {item["value"] for item in self.models(context)}:
            raise HTTPException(422, "Choose a supported memory-processing model from the catalog.")
        hashes = self.config.memory_cost_key_hashes
        active = self.config.memory_litellm_active_key_hash or (next(iter(hashes)) if len(hashes) == 1 else "")
        if not active or active not in hashes:
            raise HTTPException(503, "The active Agent Memory model key is not configured.")

        def prepare(previous: str) -> None:
            try:
                self.litellm.allow_memory_models(active, [self.config.memory_default_model, previous, data.model])
            except LiteLLMError:
                raise HTTPException(
                    503, "The memory model could not be enabled. Your setting was not changed."
                ) from None

        result, ids = self.repository.set_model(
            data.model,
            self.config.memory_default_model,
            context.user.id,
            context.user.full_name or context.user.email,
            prepare,
        )
        self.dispatcher.enqueue_immediate(ids)
        return result
