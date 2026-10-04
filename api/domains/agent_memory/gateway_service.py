import hashlib
import logging
import re
from dataclasses import dataclass
from uuid import uuid4, uuid5

from fastapi import HTTPException
from injector import inject, singleton
from pydantic import ValidationError

from api.domains.agent_memory.gateway_models import (
    MemoryAccess,
    MemoryRecall,
    MemoryReflect,
    MemoryRetain,
    OrganizationMemoryWrite,
)
from api.domains.agent_memory.repository import AgentMemoryRepository
from api.domains.agent_memory.spend_policy import MemorySpendPolicy
from api.infrastructure.hindsight.client import HindsightClient, HindsightResponse

logger = logging.getLogger(__name__)
_BANK_PATH = re.compile(r"^v1/default/banks/[^/]+/(memories/recall|memories|reflect)$")
_OPERATION_PATH = re.compile(r"^v1/default/banks/[^/]+/operations/[^/]+$")


@inject
@singleton
@dataclass
class MemoryGatewayService:
    repository: AgentMemoryRepository
    client: HindsightClient
    spend_policy: MemorySpendPolicy

    def authenticate(self, authorization: str | None) -> MemoryAccess:
        if not authorization:
            raise HTTPException(401, "Invalid Agent Memory credential.")
        scheme, _, key = authorization.partition(" ")
        if scheme.lower() != "bearer" or not key.strip() or len(key) > 256:
            raise HTTPException(401, "Invalid Agent Memory credential.")
        access = self.repository.resolve_memory_access(hashlib.sha256(key.strip().encode()).hexdigest())
        if access is None:
            raise HTTPException(401, "Invalid Agent Memory credential.")
        return access

    @staticmethod
    def accepts_payload(method: str, path: str) -> bool:
        return method == "POST" and (path == "organization-memory" or _BANK_PATH.fullmatch(path) is not None)

    def forward(self, access: MemoryAccess, method: str, path: str, payload: object) -> HindsightResponse:
        match = _BANK_PATH.fullmatch(path)
        endpoint = match.group(1) if match else "blocked"
        code = 403
        try:
            if method == "POST" and path == "organization-memory":
                endpoint = "organization-memory"
                if not access.organization_memory_write:
                    raise HTTPException(403, "Organization Memory write access is required.")
                try:
                    request = OrganizationMemoryWrite.model_validate(payload)
                except ValidationError:
                    raise HTTPException(422, "Invalid Organization Memory write.") from None
                rewritten = self._rewrite(
                    access,
                    "memories",
                    {
                        "items": [{"content": request.content, "tags": ["scope:team"]}],
                        "async": True,
                    },
                )
                self.spend_policy.require_available(access.organization_id)
                self.client.request("POST", f"/v1/default/banks/org-{access.organization_id}/memories", rewritten)
                code = 202
                return HindsightResponse(202, b'{"status":"accepted"}')
            if method == "GET" and path == "health":
                endpoint = "health"
                return HindsightResponse(200, b'{"status":"ok"}')
            if method == "GET" and path == "version":
                endpoint = "version"
                result = self.client.request("GET", "/version", None)
            elif method == "GET" and _OPERATION_PATH.fullmatch(path):
                endpoint = "operations"
                raise HTTPException(404, "Memory operation not found.")
            elif method == "POST" and match:
                rewritten = self._rewrite(access, endpoint, payload)
                if endpoint in {"memories", "reflect"}:
                    self.spend_policy.require_available(access.organization_id)
                result = self.client.request(
                    "POST", f"/v1/default/banks/org-{access.organization_id}/{endpoint}", rewritten
                )
            else:
                raise HTTPException(403, "Agent Memory operation is not allowed.")
            code = result.status_code
            return result
        except HTTPException as exc:
            code = exc.status_code
            raise
        finally:
            if endpoint == "health":
                code = 200
            logger.info(
                "Agent Memory request agent=%s organization=%s bank=org-%s endpoint=%s tags=%s status=%s",
                access.agent_id,
                access.organization_id,
                access.organization_id,
                endpoint,
                ",".join(access.readable_tags),
                code,
            )

    @staticmethod
    def _rewrite(access: MemoryAccess, endpoint: str, payload: object) -> dict:
        try:
            if endpoint == "memories":
                request = MemoryRetain.model_validate(payload)
                items = []
                for item in request.items:
                    team = "scope:team" in (item.tags or [])
                    if team and not access.organization_memory_write:
                        raise HTTPException(403, "Organization Memory write access is required.")
                    data = item.model_dump(exclude={"tags", "document_id"}, exclude_none=True)
                    data["tags"] = [f"author:{access.agent_id}", "scope:team"] if team else [f"agent:{access.agent_id}"]
                    data["observation_scopes"] = "per_tag"
                    # Scope segregation prevents an append from publishing earlier private turns.
                    document = (
                        hashlib.sha256(item.document_id.encode()).hexdigest() if item.document_id else str(uuid4())
                    )
                    data["document_id"] = f"agent:{access.agent_id}:{'team' if team else 'private'}:{document}"
                    items.append(data)
                result = {"items": items, "async": request.async_}
                if request.operation_id is not None:
                    result["operation_id"] = str(uuid5(access.agent_id, f"memory-retain:{request.operation_id}"))
                return result
            if endpoint == "memories/recall":
                result = MemoryRecall.model_validate(payload).model_dump(exclude_none=True)
                result["trace"] = False
                result["include"].update({"chunks": None, "source_facts": None})
            else:
                result = MemoryReflect.model_validate(payload).model_dump(exclude_none=True)
                result.update(
                    {
                        "apply_all_directives": False,
                        "exclude_mental_models": True,
                        "include": {"facts": None, "tool_calls": None},
                    }
                )
            # Authorship is never a private-access grant. Exact scopes also exclude
            # legacy shared facts that still carry an Agent tag until retagging.
            scopes = [
                {"tags": [tag], "match": "any_strict" if tag == "scope:team" else "exact"}
                for tag in access.readable_tags
            ]
            result["tag_groups"] = [{"or": scopes}]
            return result
        except ValidationError:
            raise HTTPException(422, "Invalid Agent Memory request.") from None
