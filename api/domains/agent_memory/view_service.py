import json
import logging
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from injector import inject, singleton
from pydantic import ValidationError

from api.core.config import Config
from api.domains.agent_memory.gateway_models import MemoryViewItem, MemoryViewPage, MemoryViewQuery
from api.domains.agent_memory.repository import AgentMemoryRepository
from api.domains.agent_memory.view_capability import MemoryViewTarget, verify_view_capability
from api.infrastructure.hindsight.client import HindsightClient

logger = logging.getLogger(__name__)
_TYPES = {"world", "experience", "observation"}


@inject
@singleton
@dataclass
class MemoryViewerService:
    """Read-only listing of the memories one Agent wrote, for authorized people.

    Authorization happened in the product API; the capability only proves that and names
    the target. Stored memories stay viewable while the Agent is stopped or memory is off.
    """

    repository: AgentMemoryRepository
    client: HindsightClient
    config: Config

    def authenticate(self, authorization: str | None) -> MemoryViewTarget:
        scheme, _, token = (authorization or "").partition(" ")
        target = (
            verify_view_capability(self.config, token.strip())
            if scheme.lower() == "bearer" and 0 < len(token.strip()) <= 2048
            else None
        )
        if target is None:
            raise HTTPException(401, "Invalid Agent Memory viewing capability.")
        if not self.repository.resolve_view_target(target.organization_id, target.agent_id):
            raise HTTPException(404, "Agent not found.")
        return target

    def list_memories(self, target: MemoryViewTarget, query: MemoryViewQuery) -> MemoryViewPage:
        own_tag = f"agent:{target.agent_id}"
        params = [
            ("tags", own_tag),
            ("tags_match", "any_strict"),
            ("limit", str(query.limit)),
            ("offset", str(query.offset)),
        ]
        if query.search:
            # Hindsight searches with ILIKE; escape its wildcards so the text matches literally.
            escaped = query.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(("q", escaped))
        code = 200
        try:
            result = self.client.request(
                "GET", f"/v1/default/banks/org-{target.organization_id}/memories/list", None, params=params
            )
            return _page(result.content, own_tag, query.limit)
        except HTTPException as exc:
            code = exc.status_code
            # Hindsight creates the Organization's bank on its first retain; before then nothing is saved.
            if exc.status_code == 404:
                return MemoryViewPage(items=[], total=0)
            raise
        finally:
            logger.info(
                "Agent Memory view agent=%s organization=%s bank=org-%s endpoint=memories/list status=%s",
                target.agent_id,
                target.organization_id,
                target.organization_id,
                code,
            )


def _page(content: bytes, own_tag: str, limit: int) -> MemoryViewPage:
    """Map upstream rows to allowlisted fields, failing closed on anything outside the contract.

    Hindsight counts `total` after applying the tag filter, so it describes only this Agent's
    rows. A row without the Agent's tag means that filter was not honored, so the count could
    include other Agents' memories and neither it nor the rows may be relayed.
    """
    try:
        body = json.loads(content)
        items = []
        for row in body["items"]:
            tags = row["tags"]
            if own_tag not in tags or row["fact_type"] not in _TYPES:
                raise ValueError("row outside the requested view")
            items.append(
                MemoryViewItem(
                    id=str(row["id"]),
                    type=row["fact_type"],
                    text=row["text"],
                    mentioned_at=_timestamp(row.get("mentioned_at")),
                    shared="scope:team" in tags,
                )
            )
        total = int(body["total"])
        if len(items) > limit or total < len(items):
            raise ValueError("page larger than requested or than its total")
        return MemoryViewPage(items=items, total=total)
    except ValueError, KeyError, TypeError, AttributeError, ValidationError:
        raise HTTPException(502, "Agent Memory backend returned an unexpected response.") from None


def _timestamp(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) and value else None
