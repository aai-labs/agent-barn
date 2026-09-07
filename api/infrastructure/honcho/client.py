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

    # How many people a shared fact is filed under, beyond the Agent itself. A
    # Slack Agent accumulates a peer per sender; past this many the fact still
    # lands on the self-model and the most established peers, and is simply not
    # scoped to every rare correspondent.
    SHARE_MAX_PEOPLE = 8

    def share_fact(self, workspace_id: str, ai_peer_name: str, content: str) -> list[dict]:
        """Store a promoted fact where the destination Agent's recall will find it.

        The two runtimes recall differently, and one placement does not serve
        both. Hermes reads the Agent's whole representation, so a conclusion on the
        self-model — `(observer, observed)` both the AI peer — is found. OpenClaw's
        plugin scopes every recall to the person it is talking to (`target:
        participantPeer`), so that same conclusion, filed as "about the Agent
        itself", is invisible there. Verified live: with the fact in its workspace,
        an OpenClaw Agent answered that it had nothing recorded.

        So the fact is written under the self-model *and* as the Agent's view of
        each person it knows. Only the Agent observes: writing it as a person's own
        self-model would assert they said it about themselves. The memory view
        collapses identical content, so an owner still sees one row.

        Posting it as a message from a synthetic peer was the first design and is
        wrong on both runtimes: Honcho stores and reasons over the message, but no
        runtime's recall ever surfaces it.
        """
        people = [p for p in self.list_peers(workspace_id) if p != ai_peer_name][: self.SHARE_MAX_PEOPLE]
        created: list[dict] = []
        for observed in [ai_peer_name, *people]:
            created.append(
                self.create_conclusion(workspace_id, content=content, observer=ai_peer_name, observed=observed)
            )
        return created

    def list_sessions(self, workspace_id: str) -> list[str]:
        payload = self._request("POST", f"/workspaces/{workspace_id}/sessions/list", json={})
        if not isinstance(payload, dict):
            return []
        raw = payload.get("items")
        items = raw if isinstance(raw, list) else []
        return [str(i.get("id")) for i in items if isinstance(i, dict) and i.get("id")]

    def delete_session(self, workspace_id: str, session_id: str) -> None:
        self._request("DELETE", f"/workspaces/{workspace_id}/sessions/{session_id}")

    def delete_workspace(self, workspace_id: str) -> None:
        """Erase an Agent's memory permanently.

        Sessions must go first: Honcho refuses a workspace delete with 409 while
        any session remains, which is the normal state for an Agent that did any
        work — verified against a live workspace. Both deletes are accepted
        asynchronously (202), so the session removals may not have landed by the
        time the workspace delete is attempted and it can still 409. That race is
        why this runs under the retrying delivery framework rather than inline in
        the request: a raised error here is retried until the purge actually takes,
        instead of leaving memory behind with nothing to report it.

        A workspace that was never created returns 404, which `_request` maps to
        None; erasing nothing is the intended outcome there, not an error.
        """
        for session_id in self.list_sessions(workspace_id):
            self.delete_session(workspace_id, session_id)
        self._request("DELETE", f"/workspaces/{workspace_id}")

    def list_all_conclusions(self, workspace_id: str, *, limit: int) -> list[dict]:
        """Every conclusion in a workspace, up to `limit`.

        Only for carrying memory over to another Agent before erasing this one.
        Bounded because an Agent's memory is unbounded and this is held in memory
        while it is copied.
        """
        collected: list[dict] = []
        page = 1
        while len(collected) < limit:
            items, total = self.list_conclusions(workspace_id, page=page, size=min(100, limit - len(collected)))
            if not items:
                break
            collected.extend(items)
            if len(collected) >= total:
                break
            page += 1
        return collected[:limit]

    def list_conclusions(
        self,
        workspace_id: str,
        *,
        page: int,
        size: int,
        observer: str | None = None,
        observed: str | None = None,
    ) -> tuple[list[dict], int]:
        """Return one page of conclusions matching the peer filter, newest first.

        Honcho filters and counts server-side, so `total` is the count for the
        filter, not the workspace — pagination under a filter is over the matches
        alone. Constraining `observer` to the Agent's own peer is what keeps the
        view to what the Agent concluded, rather than also surfacing each person's
        Honcho-derived self-model, which duplicates the same facts.
        """
        filters = {k: v for k, v in (("observer", observer), ("observed", observed)) if v}
        payload = self._request(
            "POST",
            f"/workspaces/{workspace_id}/conclusions/list",
            json={"filters": filters} if filters else {},
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
