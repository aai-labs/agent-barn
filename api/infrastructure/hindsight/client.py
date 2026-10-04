from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from fastapi import HTTPException
from injector import inject, singleton

from api.core.config import Config


@dataclass(frozen=True)
class HindsightResponse:
    status_code: int
    content: bytes


@inject
@singleton
@dataclass
class HindsightClient:
    config: Config

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None,
        *,
        params: Sequence[tuple[str, str]] | None = None,
    ) -> HindsightResponse:
        """`params` are built by the gateway; client query strings are never forwarded."""
        if not self.config.hindsight_base_url or not self.config.hindsight_api_key:
            raise HTTPException(503, "Agent Memory backend is not configured.")
        try:
            # No environment proxy, redirect, runtime headers, or client query parameters.
            with httpx.Client(timeout=self.config.hindsight_request_timeout_seconds, trust_env=False) as client:
                response = client.request(
                    method,
                    self.config.hindsight_base_url.rstrip("/") + path,
                    headers={"Authorization": f"Bearer {self.config.hindsight_api_key}"},
                    params=list(params) if params else None,
                    json=payload if method == "POST" else None,
                )
        except httpx.HTTPError:
            raise HTTPException(502, "Agent Memory backend is unavailable.") from None
        if not 200 <= response.status_code < 300:
            code = response.status_code if response.status_code in {400, 404, 409, 422, 429} else 502
            raise HTTPException(code, "Agent Memory backend rejected the request.")
        return HindsightResponse(response.status_code, response.content)
