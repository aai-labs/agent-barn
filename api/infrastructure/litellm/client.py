import base64
import logging
from dataclasses import dataclass

import httpx
from injector import inject, singleton

from api.core.config import Config
from api.infrastructure.kubernetes.client import KubernetesClient

logger = logging.getLogger(__name__)


class LiteLLMError(Exception):
    pass


class LiteLLMKeyNotFound(LiteLLMError):
    """LiteLLM has no record of the key — not the same as a key with no team."""


@inject
@dataclass
@singleton
class LiteLLMClient:
    k8s: KubernetesClient
    config: Config

    def _master_key(self) -> str:
        try:
            secret = self.k8s.get_secret(self.config.litellm_secret_name, self.config.k8s_namespace)
        except Exception as exc:
            # The Kubernetes client raises its own transport errors (urllib3, ssl,
            # kubernetes.client). Every caller here handles LiteLLMError and nothing
            # else, so letting those through turns a degraded proxy into a 500.
            raise LiteLLMError("Could not read the LiteLLM master key") from exc
        if not secret or not secret.data:
            raise LiteLLMError(f"Secret '{self.config.litellm_secret_name}' not found or empty")
        raw = secret.data.get("LITELLM_MASTER_KEY", "")
        if not raw:
            raise LiteLLMError("LITELLM_MASTER_KEY not found in litellm secret")
        if isinstance(raw, bytes):
            return raw.decode()
        return base64.b64decode(raw).decode()

    def _headers(self, master_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {master_key}",
            "Content-Type": "application/json",
        }

    _TIMEOUT = 10

    def _team_info(self, org_id: str, headers: dict[str, str]) -> dict | None:
        """The Organization's team, or None when it does not exist yet."""
        url = f"{self.config.litellm_base_url}/team/info"
        response = httpx.get(url, params={"team_id": org_id}, headers=headers, timeout=self._TIMEOUT)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        info = response.json()["team_info"]
        if info["team_id"] != org_id:
            raise ValueError("Unexpected team identity")
        return info

    def _create_team(self, org_id: str, headers: dict[str, str], policy: dict) -> None:
        created = httpx.post(
            f"{self.config.litellm_base_url}/team/new",
            json={"team_id": org_id, "team_alias": f"agentbarn-{org_id}", **policy},
            headers=headers,
            timeout=self._TIMEOUT,
        )
        # A concurrent process may have created the team first. Verify by re-reading;
        # an arbitrary 400 response is not evidence of success.
        if created.status_code not in (400, 409):
            created.raise_for_status()
        if self._team_info(org_id, headers) is None:
            raise ValueError("Team absent after creation")

    def ensure_team_exists(self, org_id: str) -> None:
        """Provision the Organization's team if it is missing, leaving policy alone.

        Deliberately never writes budget fields: this runs on the key-generation path,
        whose caller has no business re-asserting a spend policy it was not given.
        """
        try:
            headers = self._headers(self._master_key())
            if self._team_info(org_id, headers) is None:
                self._create_team(org_id, headers, {})
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise LiteLLMError("Failed to provision Organization LiteLLM team") from exc

    def apply_team_budget(self, org_id: str, max_budget: float | None, budget_duration: str | None) -> None:
        """Reconcile the team's spend policy, without disturbing spend or reset dates.

        Only changed fields are written: an update reschedules the renewal date, so
        re-sending an unchanged policy would silently move every Organization's window.
        """
        desired = {
            "max_budget": max_budget,
            "budget_duration": budget_duration if max_budget is not None else None,
        }
        try:
            headers = self._headers(self._master_key())
            current = self._team_info(org_id, headers)
            if current is None:
                self._create_team(org_id, headers, desired)
                return
            changed = {name: value for name, value in desired.items() if current.get(name) != value}
            if changed:
                response = httpx.post(
                    f"{self.config.litellm_base_url}/team/update",
                    json={"team_id": org_id, **changed},
                    headers=headers,
                    timeout=self._TIMEOUT,
                )
                response.raise_for_status()
                # Verified by re-reading, like team creation and key enrollment: some
                # versions accept an update and drop fields they do not recognise, and
                # a silently ignored clear would leave the cap enforced while the row
                # and the UI both report no limit.
                applied = self._team_info(org_id, headers) or {}
                unapplied = [name for name, value in changed.items() if applied.get(name) != value]
                if unapplied:
                    raise ValueError(f"LiteLLM did not apply {', '.join(sorted(unapplied))}")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise LiteLLMError("Failed to reconcile Organization LiteLLM team budget") from exc

    def get_team_budget_status(self, org_id: str) -> dict | None:
        """Spend accrued against the team's limit, or None when there is no team.

        This is the figure LiteLLM enforces on — deliberately not `cost_record`,
        which carries corrections LiteLLM has never seen.
        """
        try:
            info = self._team_info(org_id, self._headers(self._master_key()))
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise LiteLLMError("Failed to read Organization team spend") from exc
        if info is None:
            return None
        return {"spend": info.get("spend"), "renews_at": info.get("budget_reset_at")}

    def get_key_team(self, key: str) -> str | None:
        """The team this key belongs to, or None when it belongs to none.

        Every failure path here deliberately drops the exception chain: the key
        travels in /key/info's query string, so an httpx error would carry it into
        any traceback or log line built from the cause.
        """
        try:
            response = httpx.get(
                f"{self.config.litellm_base_url}/key/info",
                params={"key": key},
                headers=self._headers(self._master_key()),
                timeout=self._TIMEOUT,
            )
            if response.status_code == 404:
                raise LiteLLMKeyNotFound("LiteLLM does not recognise this Agent key")
            response.raise_for_status()
            return response.json()["info"].get("team_id") or None
        except LiteLLMKeyNotFound:
            raise
        except httpx.HTTPError, ValueError, KeyError, TypeError:
            raise LiteLLMError("Failed to read Agent key team membership") from None

    def attach_key_to_team(self, key: str, org_id: str) -> None:
        """Enroll an existing Agent key into its Organization's team.

        Preserves key identity, spend and blocked state. A key already in a
        different team is refused rather than moved: someone may have arranged that
        deliberately, and reassigning it silently would be worse than leaving the
        Organization partially covered.
        """
        current_team = self.get_key_team(key)
        if current_team == org_id:
            return
        if current_team:
            raise LiteLLMError("Agent key already belongs to a different LiteLLM team")
        try:
            response = httpx.post(
                f"{self.config.litellm_base_url}/key/update",
                json={"key": key, "team_id": org_id},
                headers=self._headers(self._master_key()),
                timeout=self._TIMEOUT,
            )
            response.raise_for_status()
        except httpx.HTTPError, ValueError, KeyError, TypeError:
            raise LiteLLMError("Failed to attach Agent key to Organization team") from None
        # Verified by re-reading rather than trusting the response: some LiteLLM
        # versions accept an update and drop fields they do not recognise, which
        # would otherwise report an unenrolled key as covered.
        if self.get_key_team(key) != org_id:
            raise LiteLLMError("LiteLLM did not apply the team assignment")

    def generate_key(self, agent_id: str, agent_name: str, org_id: str) -> str:
        """Returns a new plaintext LiteLLM key for the agent."""
        self.ensure_team_exists(org_id)
        master_key = self._master_key()
        url = f"{self.config.litellm_base_url}/key/generate"
        try:
            resp = httpx.post(
                url,
                json={
                    "key_alias": f"{agent_name}-{agent_id}",
                    "team_id": org_id,
                    "metadata": {
                        "agent_id": agent_id,
                        "organization_id": org_id,
                    },
                },
                headers=self._headers(master_key),
                timeout=10,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LiteLLMError(f"LiteLLM key generation failed: {exc}") from exc
        key = resp.json().get("key")
        if not key:
            raise LiteLLMError(f"LiteLLM returned no key: {resp.text}")
        return key

    def delete_key(self, key: str) -> bool:
        """Deletes a LiteLLM virtual key outright. Returns True only for a
        successful LiteLLM response; callers should treat False as failure and
        fall back to block_key so the key can no longer be used even if it
        can't be removed. Never logs the plaintext key.
        """
        try:
            master_key = self._master_key()
            resp = httpx.post(
                f"{self.config.litellm_base_url}/key/delete",
                json={"keys": [key]},
                headers=self._headers(master_key),
                timeout=10,
            )
            resp.raise_for_status()
        except Exception as exc:
            # Do not include the exception text: some HTTP/client exceptions can
            # carry request details, and the request contains the plaintext key.
            logger.warning("Failed to delete LiteLLM key: %s", type(exc).__name__)
            return False
        return True

    def block_key(self, key: str) -> None:
        try:
            master_key = self._master_key()
            resp = httpx.post(
                f"{self.config.litellm_base_url}/key/block",
                json={"key": key},
                headers=self._headers(master_key),
                timeout=10,
            )
            resp.raise_for_status()
        except Exception as exc:
            # Keep this best-effort path secret-safe even for client exceptions
            # that may include request details.
            logger.warning("Failed to block LiteLLM key: %s", type(exc).__name__)

    def get_key_info(self, key: str) -> dict:
        """Return the full key info dict from LiteLLM (spend, token totals, etc)."""
        master_key = self._master_key()
        try:
            resp = httpx.get(
                f"{self.config.litellm_base_url}/key/info",
                params={"key": key},
                headers=self._headers(master_key),
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            # LiteLLM returns {"info": {"spend": 0.001234, "total_tokens": 123, ...}}
            info = data.get("info", {})
            return info
        except Exception as exc:
            raise LiteLLMError(f"Failed to fetch key info: {exc}") from exc

    def get_key_spend(self, key: str) -> float:
        """Return the total spend (USD) accumulated by this virtual key."""
        return float(self.get_key_info(key).get("spend", 0.0))

    def get_key_spend_details(self, key: str) -> dict:
        """
        Return spend + token totals for a virtual key using /spend/keys.
        Returns a dict with keys: spend, total_input_tokens, total_output_tokens.
        Falls back to /key/info spend if /spend/keys doesn't return matching data.
        """
        import hashlib

        key_hash = hashlib.sha256(key.encode()).hexdigest()

        master_key = self._master_key()
        try:
            resp = httpx.get(
                f"{self.config.litellm_base_url}/spend/keys",
                params={"key": key},
                headers=self._headers(master_key),
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            entries = data if isinstance(data, list) else [data]
            for entry in entries:
                # LiteLLM stores the SHA256 hash of the raw key in the 'token' field.
                if entry.get("token") == key_hash:
                    return {
                        "spend": float(entry.get("spend", 0.0)),
                        "total_input_tokens": int(entry.get("total_input_tokens", 0) or 0),
                        "total_output_tokens": int(entry.get("total_output_tokens", 0) or 0),
                    }
            logger.warning("LiteLLM /spend/keys: no entry matched key hash %s...", key_hash[:8])
        except Exception as exc:
            logger.warning("Failed to fetch /spend/keys for token counts: %s", exc)

        # Fallback: use /key/info for spend, tokens unavailable
        info = self.get_key_info(key)
        return {
            "spend": float(info.get("spend", 0.0)),
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }

    def get_spend_logs(self, key: str, start_date: str, end_date: str, limit: int = 10) -> list[dict]:
        """Return per-request spend log rows for the given key and date range."""
        master_key = self._master_key()
        try:
            resp = httpx.get(
                f"{self.config.litellm_base_url}/spend/logs",
                params={
                    "api_key": key,
                    "start_date": start_date,
                    "end_date": end_date,
                    "limit": limit,
                },
                headers=self._headers(master_key),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            logs = data if isinstance(data, list) else data.get("logs", [])
            return logs
        except Exception as exc:
            raise LiteLLMError(f"Failed to fetch spend logs: {exc}") from exc

    def get_spend_logs_v2(
        self,
        start_date: str,
        end_date: str,
        page: int = 1,
        page_size: int = 1000,
    ) -> dict:
        """Return one page of per-request spend logs.

        This is LiteLLM's paginated public spend API. `/spend/logs` is deprecated and
        aggregates rather than listing rows; `/spend/logs/ui` is internal and absent
        from the OpenAPI schema, so neither is safe to depend on in client-deployed
        installs. `/spend/logs/v2` is present in v1.83 and v1.96 alike.

        Dates must be `YYYY-MM-DD HH:MM:SS` — a bare date returns HTTP 400.

        Rows come back oldest-first. That is deliberate and load-bearing: the sync
        watermark is `max(occurred_at)` of what we have stored, so ascending order
        makes the watermark double as a resume cursor. Under LiteLLM's default
        `desc`, a run that stopped partway would land only the newest rows, push the
        watermark to ~now, and skip everything older for good.

        Returns the raw envelope: {data, total, page, page_size, total_pages,
        total_is_capped}.
        """
        master_key = self._master_key()
        try:
            resp = httpx.get(
                f"{self.config.litellm_base_url}/spend/logs/v2",
                params={
                    "start_date": start_date,
                    "end_date": end_date,
                    "page": page,
                    "page_size": page_size,
                    "sort_by": "startTime",
                    "sort_order": "asc",
                },
                headers=self._headers(master_key),
                timeout=60,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LiteLLMError(f"Failed to fetch spend logs page {page}: {exc}") from exc
        payload = resp.json()
        if not isinstance(payload, dict):
            raise LiteLLMError(f"Unexpected /spend/logs/v2 response type: {type(payload).__name__}")
        return payload
