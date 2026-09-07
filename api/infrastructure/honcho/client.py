import logging
from dataclasses import dataclass

import httpx
from injector import inject, singleton

from api.core.config import Config

logger = logging.getLogger(__name__)


def workspace_id_for_agent(agent_id: object) -> str:
    """Derive a Honcho workspace name from the Agent id.

    Deriving it rather than storing it means workspace ownership needs no
    mapping row: any code that has the Agent id can name its workspace.
    """
    return f"af-{agent_id}"


class HonchoError(Exception):
    """Honcho rejected a request or could not be reached."""


@inject
@dataclass
@singleton
class HonchoClient:
    """Writes promoted facts into another Agent's Honcho workspace.

    Deliberately narrow: this is not a general Honcho client. It exists to
    support explicit cross-Agent memory sharing, not to read or manage memory.
    """

    config: Config

    @property
    def _base(self) -> str:
        return f"{self.config.honcho_base_url.rstrip('/')}/v3"

    def share_fact(self, workspace_id: str, ai_peer_name: str, content: str) -> dict:
        """Store a promoted fact as something the destination Agent knows.

        Written as a conclusion on the Agent's own self-model — `(observer,
        observed)` both being its AI peer — because that is where its recall
        actually looks. Posting a message from a synthetic peer into a separate
        session stores the fact and lets Honcho reason over it, but the runtime's
        own recall never surfaces it: verified against a live Agent, which
        answered from a directly written conclusion and not from a message.

        Shared knowledge is also genuinely the Agent's own rather than an
        observation about a person, and self-model avoids guessing a user peer
        name, which differs per runtime and per message sender.
        """
        return self.create_conclusion(workspace_id, content=content, observer=ai_peer_name, observed=ai_peer_name)

    def list_conclusions(self, workspace_id: str, *, page: int, size: int) -> tuple[list[dict], int]:
        """Return one page of an Agent's conclusions, newest first."""
        payload = self._request(
            "POST",
            f"/workspaces/{workspace_id}/conclusions/list",
            json={},
            params={"page": page, "size": size},
        )
        # A workspace only exists once an Agent has conversed. Nothing learned
        # yet is an empty view, not an error.
        if not isinstance(payload, dict):
            return [], 0
        raw_items = payload.get("items")
        items: list[dict] = [i for i in raw_items if isinstance(i, dict)] if isinstance(raw_items, list) else []
        raw_total = payload.get("total")
        return items, raw_total if isinstance(raw_total, int) else len(items)

    def delete_conclusion(self, workspace_id: str, conclusion_id: str) -> None:
        self._request("DELETE", f"/workspaces/{workspace_id}/conclusions/{conclusion_id}")

    def create_conclusion(self, workspace_id: str, *, content: str, observer: str, observed: str) -> dict:
        """Store an operator-authored conclusion.

        Honcho has no update endpoint, so a correction is a delete followed by
        this. The replacement is always `explicit` — the level cannot be supplied
        on create — which is arguably right for something a human asserted, but it
        does mean a corrected deduction stops looking like a deduction.
        """
        payload = self._request(
            "POST",
            f"/workspaces/{workspace_id}/conclusions",
            json={"conclusions": [{"content": content, "observer_id": observer, "observed_id": observed}]},
        )
        created = payload if isinstance(payload, list) else []
        if not created or not isinstance(created[0], dict):
            raise HonchoError("Honcho accepted the conclusion but returned nothing usable")
        return created[0]

    def _request(self, method: str, path: str, **kwargs) -> object:
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.request(method, f"{self._base}{path}", **kwargs)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return response.json() if response.content else None
        except httpx.HTTPError as exc:
            raise HonchoError(f"Honcho request failed ({method} {path}): {exc}") from exc

    def search_conclusions(
        self, workspace_id: str, *, query: str, observer: str, observed: str, top_k: int
    ) -> list[dict]:
        """Semantic search within one (observer, observed) collection.

        Honcho rejects a search that does not name both peers: the vectors are
        stored per pair, so there is no index spanning them. Searching an Agent's
        whole memory therefore means searching each pair and merging.
        """
        payload = self._request(
            "POST",
            f"/workspaces/{workspace_id}/conclusions/query",
            json={
                "query": query,
                "top_k": top_k,
                "filters": {"observer": observer, "observed": observed},
            },
        )
        items = payload if isinstance(payload, list) else []
        return [i for i in items if isinstance(i, dict)]

    def list_peers(self, workspace_id: str) -> list[str]:
        payload = self._request("POST", f"/workspaces/{workspace_id}/peers/list", json={})
        if not isinstance(payload, dict):
            return []
        raw = payload.get("items")
        items = raw if isinstance(raw, list) else []
        return [str(i.get("id")) for i in items if isinstance(i, dict) and i.get("id")]
