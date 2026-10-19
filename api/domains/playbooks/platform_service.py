from dataclasses import dataclass

from fastapi import HTTPException
from injector import inject, singleton

from api.core.config import Config
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher
from api.domains.platform_admin.service import PlatformAdminService
from api.domains.playbooks.platform_models import PlatformPlaybookSettingsRead, PlatformPlaybookSettingsUpdate
from api.domains.playbooks.platform_repository import PlatformPlaybookRepository
from api.infrastructure.openrouter.client import OpenRouterClient, OpenRouterError


@inject
@singleton
@dataclass
class PlatformPlaybookService:
    """The model every Organization's Playbook Extractions use.

    Runs are billed to the source Agent's own LiteLLM key, which allows any model, so
    no key allowlist needs updating and Organization model allowlists do not apply.
    """

    repository: PlatformPlaybookRepository
    authority: PlatformAdminService
    catalog: OpenRouterClient
    config: Config
    dispatcher: EventDeliveryDispatcher

    def current_model(self) -> str:
        return self.repository.read(self.config.playbook_default_model).model

    def read(self, context: CurrentUserContext) -> PlatformPlaybookSettingsRead:
        self.authority.require_platform_admin(context.user)
        return self.repository.read(self.config.playbook_default_model)

    def models(self, context: CurrentUserContext) -> list[dict[str, str]]:
        self.authority.require_platform_admin(context.user)
        try:
            models = self.catalog.list_models()
        except OpenRouterError:
            raise HTTPException(503, "The model catalog is unavailable.") from None
        # Extraction reads text and writes Markdown; it needs nothing else.
        return [
            {"value": f"openrouter/{m['id']}", "label": m["name"]}
            for m in models
            if "text" in m.get("output_modalities", [])
        ]

    def update(self, data: PlatformPlaybookSettingsUpdate, context: CurrentUserContext) -> PlatformPlaybookSettingsRead:
        self.authority.require_platform_admin(context.user)
        if data.model not in {item["value"] for item in self.models(context)}:
            raise HTTPException(422, "Choose a supported model from the catalog.")
        result, ids = self.repository.set_model(
            data.model,
            self.config.playbook_default_model,
            context.user.id,
            context.user.full_name or context.user.email,
        )
        self.dispatcher.enqueue_immediate(ids)
        return result
