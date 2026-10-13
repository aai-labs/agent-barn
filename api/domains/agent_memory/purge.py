"""Operator/CronJob-only cleanup of deleted Agents' Hindsight documents."""

import json
import logging
import time
from dataclasses import dataclass
from urllib.parse import quote

from fastapi import HTTPException
from injector import inject

from api.core.config import Config
from api.domains.agent_memory.models import AgentMemoryPurge
from api.domains.agent_memory.purge_repository import MemoryPurgeRepository
from api.infrastructure.hindsight.client import HindsightClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

logger = logging.getLogger(__name__)
MAX_RUNTIME_SECONDS = 240
MAX_TASKS = 20
MAX_DOCUMENTS = 100


@inject
@dataclass
class MemoryPurger:
    repository: MemoryPurgeRepository
    client: HindsightClient

    def run_once(self) -> int:
        deadline = time.monotonic() + MAX_RUNTIME_SECONDS
        cleaned = 0
        for _ in range(MAX_TASKS):
            if time.monotonic() >= deadline:
                break
            row = self.repository.claim()
            if row is None:
                break
            error = None
            try:
                if not self.repository.can_purge(row):
                    error = "target_not_deleted"
                else:
                    self.purge(row, deadline)
            except HTTPException as exc:
                error = f"backend_{exc.status_code}"
            except ValueError, KeyError, TypeError:
                error = "invalid_backend_response"
            except Exception:
                # Never log memory text, document IDs, raw upstream errors, or secrets.
                error = "cleanup_failed"
            self.repository.finish(row, error)
            cleaned += int(error is None)
            logger.info(
                "Agent Memory purge agent=%s organization=%s result=%s",
                row.agent_id,
                row.organization_id,
                error or "clean",
            )
        return cleaned

    def purge(self, row: AgentMemoryPurge, deadline: float) -> None:
        """Delete bounded pages at offset zero so deletions cannot skip subsequent documents."""
        bank = f"/v1/default/banks/org-{row.organization_id}"
        tag = f"agent:{row.agent_id}"
        for _ in range(MAX_DOCUMENTS):
            if time.monotonic() >= deadline:
                raise HTTPException(503, "Cleanup run reached its deadline.")
            try:
                response = self.client.request(
                    "GET",
                    bank + "/documents",
                    None,
                    params=[
                        ("tags", tag),
                        ("tags", f"author:{row.agent_id}"),
                        ("tags_match", "any_strict"),
                        ("limit", "1"),
                        ("offset", "0"),
                    ],
                )
            except HTTPException as exc:
                if exc.status_code == 404:
                    return  # No bank: nothing has been retained.
                raise
            body = json.loads(response.content)
            items = body["items"]
            if not isinstance(items, list) or len(items) > 1:
                raise ValueError("invalid document page")
            if not items:
                if body["total"] != 0:
                    raise ValueError("inconsistent document count")
                return
            doc = items[0]
            document_id = doc["id"]
            if not isinstance(document_id, str) or not document_id.startswith((tag + ":private:", tag + ":team:")):
                raise ValueError("document outside Agent namespace")
            if not isinstance(doc["tags"], list) or not {tag, f"author:{row.agent_id}"}.intersection(doc["tags"]):
                raise ValueError("document outside Agent tags")
            try:
                result = self.client.request("DELETE", bank + "/documents/" + quote(document_id, safe=""), None)
            except HTTPException as exc:
                if exc.status_code == 404:
                    continue  # Another sweep removed it.
                raise
            if json.loads(result.content).get("success") is not True:
                raise ValueError("delete did not confirm success")
        raise HTTPException(503, "Cleanup batch reached its document limit.")


def main() -> None:
    # The job has a bounded runtime and no need to wait through an extraction timeout.
    # This operator process does not authenticate people or bootstrap an admin.
    # Do not require their signing key/credentials just to load shared settings.
    # Cleanup never creates an Organization or Agent, so creation-budget defaults
    # are unused. Keep this operator's environment limited to DB and backend access.
    config = Config(
        secret_signing_key="",
        platform_admin_credentials="",
        organization_default_llm_budget_usd=0,
        agent_default_llm_budget_usd=0,
    )
    config.hindsight_request_timeout_seconds = min(10, config.hindsight_request_timeout_seconds)
    logging.basicConfig(level=logging.INFO)
    delegate = PostgresRepositoryDelegate(config)
    try:
        MemoryPurger(MemoryPurgeRepository(delegate), HindsightClient(config)).run_once()
    finally:
        delegate.close()
