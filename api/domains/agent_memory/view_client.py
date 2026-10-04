from dataclasses import dataclass
from uuid import UUID

import httpx
from fastapi import HTTPException
from injector import inject, singleton
from pydantic import ValidationError

from api.core.config import Config
from api.domains.agent_memory.gateway_models import MemoryViewPage
from api.domains.agent_memory.view_capability import issue_view_capability


@inject
@singleton
@dataclass
class MemoryViewClient:
    """Asks the memory gateway's read-only viewer for Agent history or shared Organization memories.

    The product API holds no Hindsight credential: it sends a short-lived capability for
    one authorized Agent or Organization target, and the gateway derives the bank and tag filter itself.
    """

    config: Config

    def list_memories(
        self, organization_id: UUID, agent_id: UUID | None, *, search: str | None, limit: int, offset: int
    ) -> MemoryViewPage:
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if search:
            params["search"] = search
        try:
            # No environment proxy or redirect: the capability goes only to the configured gateway.
            with httpx.Client(timeout=self.config.hindsight_request_timeout_seconds, trust_env=False) as client:
                response = client.get(
                    self.config.memory_view_base_url.rstrip("/") + "/memories",
                    params=params,
                    headers={
                        "Authorization": f"Bearer {issue_view_capability(self.config, organization_id, agent_id)}"
                    },
                )
        except httpx.HTTPError:
            raise HTTPException(503, "Agent Memory is unavailable.") from None
        if response.status_code == 404:
            raise HTTPException(404, "Organization not found" if agent_id is None else f"Agent {agent_id} not found")
        if response.status_code != 200:
            raise HTTPException(503 if response.status_code == 503 else 502, "Agent Memory is unavailable.")
        try:
            return MemoryViewPage.model_validate_json(response.content)
        except ValidationError:
            raise HTTPException(502, "Agent Memory returned an unexpected response.") from None
