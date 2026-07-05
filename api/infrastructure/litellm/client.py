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


@inject
@dataclass
@singleton
class LiteLLMClient:
    k8s: KubernetesClient
    config: Config

    def _master_key(self) -> str:
        secret = self.k8s.get_secret(
            self.config.litellm_secret_name, self.config.k8s_namespace
        )
        if not secret or not secret.data:
            raise LiteLLMError(
                f"Secret '{self.config.litellm_secret_name}' not found or empty"
            )
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

    def generate_key(self, agent_id: str, agent_name: str) -> str:
        master_key = self._master_key()
        url = f"{self.config.litellm_base_url}/key/generate"
        try:
            resp = httpx.post(
                url,
                json={
                    "key_alias": agent_name,
                    "metadata": {"agent_id": agent_id, "agent_name": agent_name},
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

    def delete_key(self, key: str) -> None:
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
            logger.warning("Failed to delete LiteLLM key: %s", exc)

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
            logger.warning("Failed to block LiteLLM key: %s", exc)

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
                        "total_input_tokens": int(
                            entry.get("total_input_tokens", 0) or 0
                        ),
                        "total_output_tokens": int(
                            entry.get("total_output_tokens", 0) or 0
                        ),
                    }
            logger.warning(
                "LiteLLM /spend/keys: no entry matched key hash %s...", key_hash[:8]
            )
        except Exception as exc:
            logger.warning("Failed to fetch /spend/keys for token counts: %s", exc)

        # Fallback: use /key/info for spend, tokens unavailable
        info = self.get_key_info(key)
        return {
            "spend": float(info.get("spend", 0.0)),
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }

    def get_spend_logs(
        self, key: str, start_date: str, end_date: str, limit: int = 10
    ) -> list[dict]:
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

    def get_global_spend_report(
        self, start_date: str, end_date: str
    ) -> dict[str, dict]:
        """
        Fetch aggregated spend+token data per API key hash using /user/daily/activity/aggregated.
        Returns: {
            "key_hash": {
                "spend": 0.0, "total_input_tokens": 0, "total_output_tokens": 0, "total_tokens": 0,
                "daily_spend": {"2026-06-23": 0.01},
                "models": {
                    "openrouter/qwen/qwen3.6-plus": {"spend": 0.0, "prompt_tokens": 0, "completion_tokens": 0}
                }
            }
        }
        """
        master_key = self._master_key()
        aggregated: dict[str, dict] = {}
        try:
            resp = httpx.get(
                f"{self.config.litellm_base_url}/user/daily/activity/aggregated",
                params={"start_date": start_date, "end_date": end_date},
                headers=self._headers(master_key),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            for day in results:
                date_str = day.get("date")
                api_keys = day.get("breakdown", {}).get("api_keys", {})
                for key_hash, key_data in api_keys.items():
                    if key_hash == "no-key-required":
                        continue
                    metrics = key_data.get("metrics", {})
                    if key_hash not in aggregated:
                        aggregated[key_hash] = {
                            "spend": 0.0,
                            "total_input_tokens": 0,
                            "total_output_tokens": 0,
                            "total_tokens": 0,
                            "daily_spend": {},
                            "models": {},  # <-- THIS WAS MISSING
                        }
                    day_spend = float(metrics.get("spend") or 0.0)
                    aggregated[key_hash]["spend"] += day_spend
                    aggregated[key_hash]["total_input_tokens"] += int(
                        metrics.get("prompt_tokens") or 0
                    )
                    aggregated[key_hash]["total_output_tokens"] += int(
                        metrics.get("completion_tokens") or 0
                    )
                    aggregated[key_hash]["total_tokens"] += int(
                        metrics.get("total_tokens") or 0
                    )
                    if date_str:
                        existing = aggregated[key_hash]["daily_spend"].get(
                            date_str, 0.0
                        )
                        aggregated[key_hash]["daily_spend"][date_str] = (
                            existing + day_spend
                        )

                    # Per-model breakdown for this key  <-- THIS BLOCK WAS MISSING
                    models_in_day = day.get("breakdown", {}).get("models", {})
                    for model_name, model_data in models_in_day.items():
                        model_api_keys = model_data.get("api_key_breakdown", {})
                        if key_hash not in model_api_keys:
                            continue
                        m_metrics = model_api_keys[key_hash].get("metrics", {})
                        if model_name not in aggregated[key_hash]["models"]:
                            aggregated[key_hash]["models"][model_name] = {
                                "spend": 0.0,
                                "prompt_tokens": 0,
                                "completion_tokens": 0,
                            }
                        aggregated[key_hash]["models"][model_name]["spend"] += float(
                            m_metrics.get("spend") or 0.0
                        )
                        aggregated[key_hash]["models"][model_name]["prompt_tokens"] += (
                            int(m_metrics.get("prompt_tokens") or 0)
                        )
                        aggregated[key_hash]["models"][model_name][
                            "completion_tokens"
                        ] += int(m_metrics.get("completion_tokens") or 0)

            return aggregated
        except Exception as exc:
            logger.warning("Failed to fetch aggregated daily activity: %s", exc)
            return {}
