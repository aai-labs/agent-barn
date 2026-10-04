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
    """Read-only permission-scoped Agent memory or Organization Memory for authorized people.

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
            raise HTTPException(404, "Organization not found." if target.agent_id is None else "Agent not found.")
        return target

    def list_memories(self, target: MemoryViewTarget, query: MemoryViewQuery) -> MemoryViewPage:
        if target.agent_id is None:
            return self._list_scope(target, query, "scope:team", exact=False)
        # Private first, then Organization Memory. Disjoint scopes make counts and
        # pagination exact without downloading the bank or post-filtering a page.
        private = self._list_scope(target, query, f"agent:{target.agent_id}", exact=True)
        if not self.repository.has_organization_memory_read(target.organization_id, target.agent_id):
            return private
        shared = self._list_scope(
            target,
            MemoryViewQuery(
                search=query.search,
                limit=query.limit - len(private.items) or 1,
                offset=max(0, query.offset - private.total),
            ),
            "scope:team",
            exact=False,
            count_only=len(private.items) == query.limit,
        )
        return MemoryViewPage(items=private.items + shared.items, total=private.total + shared.total)

    def _list_scope(
        self, target: MemoryViewTarget, query: MemoryViewQuery, tag: str, *, exact: bool, count_only: bool = False
    ) -> MemoryViewPage:
        limit = 0 if count_only else query.limit
        params = [
            ("tags", tag),
            ("tags_match", "exact" if exact else "any_strict"),
            ("limit", str(limit)),
            ("offset", str(query.offset)),
        ]
        if query.search:
            escaped = query.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(("q", escaped))
        code = 200
        try:
            result = self.client.request(
                "GET", f"/v1/default/banks/org-{target.organization_id}/memories/list", None, params=params
            )
            return _page(result.content, tag, limit, exact=exact)
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


def _page(content: bytes, own_tag: str, limit: int, *, exact: bool = False) -> MemoryViewPage:
    """Map upstream rows to allowlisted fields, failing closed on anything outside the contract.

    Hindsight counts `total` after applying the derived tag filter. A row without
    that tag means the filter was not honored; neither rows nor counts may be relayed.
    """
    try:
        body = json.loads(content)
        items = []
        for row in body["items"]:
            tags = row["tags"]
            if own_tag not in tags or (exact and set(tags) != {own_tag}) or row["fact_type"] not in _TYPES:
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
