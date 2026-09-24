import datetime
import logging
from dataclasses import dataclass

import httpx
import jwt
from injector import inject, singleton

from api.core.config import Config

logger = logging.getLogger(__name__)


def mint_admin_token(jwt_secret: str) -> str:
    """Sign a Honcho admin JWT (full access) for the API's cross-pool calls.

    Mirrors Honcho's own `create_admin_jwt` — claims `{"t": "", "ad": true}`,
    HS256 over the shared `AUTH_JWT_SECRET`. The API manages every pool (list,
    search, curate, share across pools, delete a pool), so it needs the admin key,
    not a workspace-scoped one.
    """
    return jwt.encode({"t": "", "ad": True}, jwt_secret.encode("utf-8"), algorithm="HS256")


def mint_workspace_token(jwt_secret: str, workspace_id: str) -> str:
    """Sign a Honcho JWT scoped to one workspace, for an Agent pod.

    Mirrors Honcho's `create_jwt`/`JWTParams` — claims `{"t": <iso>, "w": <ws>}`,
    HS256 over the shared secret. A workspace-scoped token reaches every peer and
    session in that pool and nothing outside it, so a pod (even a prompt-injected
    one) can only touch its own pool. No `exp`: the token is re-minted on every
    (re)provision, and changing pools reprovisions with a new one.
    """
    return jwt.encode(
        {"t": datetime.datetime.now(datetime.UTC).isoformat(), "w": workspace_id},
        jwt_secret.encode("utf-8"),
        algorithm="HS256",
    )


POOL_WORKSPACE_PREFIX = "af-pool-"


def workspace_id_for_pool(pool_id: object) -> str:
    """Derive the shared Honcho workspace name for a memory pool.

    A pool is one workspace shared by every opted-in Agent in it, so they can
    see each other's memory. The `af-pool-` prefix keeps pool workspaces
    distinguishable from legacy per-Agent `af-<uuid>` workspaces (cost
    attribution relies on telling them apart — see `pool_id_from_workspace`).
    """
    return f"{POOL_WORKSPACE_PREFIX}{pool_id}"


def pool_id_from_workspace(workspace_id: str) -> str | None:
    """Recover a pool id from a pool workspace name, or None if it is not one.

    Returns None for legacy per-Agent workspaces (`af-<uuid>`) so callers that
    aggregate cost per pool never mistake an old per-Agent workspace for a pool.
    """
    if workspace_id.startswith(POOL_WORKSPACE_PREFIX):
        return workspace_id[len(POOL_WORKSPACE_PREFIX) :]
    return None


class HonchoError(Exception):
    """Honcho rejected a request or could not be reached."""


@inject
@dataclass
@singleton
class HonchoClient:
    """The API's client for a memory pool's Honcho workspace.

    Reads and curates pooled memory (list/search/find/correct/forget), ensures the
    workspace and its peers, sets deriver instructions, copies shared facts across
    pools, and erases a pool when its group is deleted.
    """

    config: Config

    @property
    def _base(self) -> str:
        return f"{self.config.honcho_base_url.rstrip('/')}/v3"

    def share_fact(self, workspace_id: str, share_peer: str, content: str, *, subject: str) -> list[dict]:
        """Copy a promoted fact into a pool, preserving what it is *about*.

        Filed as `(observer=share_peer, observed=subject)` — the subject is the
        original conclusion's `observed` (e.g. "operator") — so the memory view and
        recall keep it about that subject instead of turning a fact about the
        operator into the curator's own self-model, which is what filing it as
        `(share_peer, share_peer)` did.

        One conclusion is enough: both runtimes now recall pool-wide via the
        workspace-level dialectic (the honcho-pool-recall patch/plugin), so the old
        self-model + per-person fan-out — which existed only for OpenClaw's former
        per-participant recall — is no longer needed.

        A target pool can be brand new, and Honcho auto-creates neither the
        workspace nor peers, so the workspace and both the observer and observed
        peers are ensured first (idempotent get-or-create) or the write 404s.
        """
        self._request("POST", "/workspaces", json={"id": workspace_id})
        self._request("POST", f"/workspaces/{workspace_id}/peers", json={"id": share_peer})
        if subject != share_peer:
            self._request("POST", f"/workspaces/{workspace_id}/peers", json={"id": subject})
        return [self.create_conclusion(workspace_id, content=content, observer=share_peer, observed=subject)]

    # Told to the deriver, per workspace, to keep it from recording transient
    # conversational actions ("the peer asked X") as durable facts. Honcho's base
    # extraction prompt says "extract ALL observations", so without this a question
    # becomes a memory; measured live, it cut a mixed message from three
    # conclusions to the one real fact.
    DERIVER_INSTRUCTIONS = (
        "Record only durable facts, preferences, decisions, and commitments about the peer. "
        "Do not record that the peer asked a question, requested something, greeted, or that a "
        "message was sent — transient conversational actions are not facts worth remembering."
    )

    def ensure_deriver_instructions(self, workspace_id: str, instructions: str) -> None:
        """Set the deriver's custom instructions on a workspace, creating it if needed.

        The runtime creates the workspace lazily on first conversation, so this
        both creates it (idempotent get-or-create) and sets the configuration —
        the create call does not update an already-existing workspace's config, so
        the update is sent explicitly and also backfills workspaces that predate
        this. Configuration resolves workspace-wide, below any per-session override.
        """
        body = {"configuration": {"reasoning": {"custom_instructions": instructions}}}
        # get-or-create; on a brand-new workspace this already applies the config.
        self._request("POST", "/workspaces", json={"id": workspace_id, **body})
        # explicit update so an existing workspace picks it up too.
        self._request("PUT", f"/workspaces/{workspace_id}", json=body)

    def list_sessions(self, workspace_id: str) -> list[str]:
        payload = self._request("POST", f"/workspaces/{workspace_id}/sessions/list", json={})
        if not isinstance(payload, dict):
            return []
        raw = payload.get("items")
        items = raw if isinstance(raw, list) else []
        return [str(i.get("id")) for i in items if isinstance(i, dict) and i.get("id")]

    def delete_session(self, workspace_id: str, session_id: str) -> None:
        self._request("DELETE", f"/workspaces/{workspace_id}/sessions/{session_id}")

    def delete_pool_workspace(self, workspace_id: str) -> None:
        """Delete a memory pool's workspace, deliberately.

        The one sanctioned path to erase shared memory, used when a memory group is
        deleted. Sessions go first: Honcho refuses a workspace delete with 409 while
        any session remains (the normal state for a pool that did any work), and both
        deletes are async 202s, so the workspace delete can still 409 until the
        session removals land — the caller (`delete_group`) retries past that race. A
        workspace that never existed 404s, which `_request` maps to None: erasing
        nothing is the intended outcome, not an error.
        """
        self._delete_workspace_unchecked(workspace_id)

    def _delete_workspace_unchecked(self, workspace_id: str) -> None:
        # Sessions first (Honcho 409s on a workspace delete while any remain);
        # both deletes are async 202, so the caller retries until it takes.
        for session_id in self.list_sessions(workspace_id):
            self.delete_session(workspace_id, session_id)
        self._request("DELETE", f"/workspaces/{workspace_id}")

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

    def find_conclusion(
        self, workspace_id: str, conclusion_id: str, *, observer: str | None = None, observed: str | None = None
    ) -> dict | None:
        """Locate one conclusion by id, or None if it is not in the workspace.

        Honcho exposes no get-by-id for conclusions, so this walks pages. Passing
        the `(observer, observed)` the caller already has scopes the walk to that
        one collection instead of the whole pool, so the page cap is reached far
        later — an old item in a large pool is still found rather than missed.
        """
        for page in range(1, 21):
            items, total = self.list_conclusions(
                workspace_id, page=page, size=100, observer=observer, observed=observed
            )
            for item in items:
                if str(item.get("id")) == conclusion_id:
                    return item
            if not items or page * 100 >= total:
                return None
        return None

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

    @property
    def _auth_headers(self) -> dict[str, str]:
        """Admin bearer for the API's calls when Honcho auth is on; empty otherwise.

        Empty secret means auth is disabled (dev), so no header is sent and Honcho
        serves unauthenticated — keeping the layer usable without auth locally."""
        secret = self.config.honcho_jwt_secret
        return {"Authorization": f"Bearer {mint_admin_token(secret)}"} if secret else {}

    def _request(self, method: str, path: str, **kwargs) -> object:
        headers = {**self._auth_headers, **kwargs.pop("headers", {})}
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.request(method, f"{self._base}{path}", headers=headers, **kwargs)
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
