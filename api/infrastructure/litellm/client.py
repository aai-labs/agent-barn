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
        secret = self.k8s.get_secret(self.config.litellm_secret_name, self.config.k8s_namespace)
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

    def generate_key(self, agent_id: str) -> str:
        master_key = self._master_key()
        url = f"{self.config.litellm_base_url}/key/generate"
        try:
            resp = httpx.post(
                url,
                json={"metadata": {"agent_id": agent_id}},
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
            logger.warning("Failed to revoke LiteLLM key: %s", exc)
