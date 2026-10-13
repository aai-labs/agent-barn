"""Chat completions through the LiteLLM proxy, billed to the virtual key the caller supplies."""

import enum
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx
from injector import inject, singleton

from api.core.config import Config


class CompletionFailure(str, enum.Enum):
    BUDGET_EXCEEDED = "budget_exceeded"
    KEY_OR_MODEL_REJECTED = "key_or_model_rejected"
    UNAVAILABLE = "unavailable"
    BAD_RESPONSE = "bad_response"


class CompletionError(Exception):
    """A completion that did not produce text. Never carries request or response content."""

    def __init__(self, failure: CompletionFailure) -> None:
        super().__init__(failure.value)
        self.failure = failure


@dataclass(frozen=True)
class CompletionResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal | None


@inject
@singleton
@dataclass
class LiteLLMCompletionClient:
    config: Config

    def complete(
        self,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        json_response: bool = False,
        timeout_seconds: float = 180,
    ) -> CompletionResult:
        body: dict[str, object] = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}
        if json_response:
            body["response_format"] = {"type": "json_object"}
        try:
            # No environment proxy or redirect: the key goes only to the configured proxy.
            with httpx.Client(timeout=timeout_seconds, trust_env=False, follow_redirects=False) as client:
                response = client.post(
                    f"{self.config.litellm_base_url.rstrip('/')}/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
        except httpx.HTTPError:
            raise CompletionError(CompletionFailure.UNAVAILABLE) from None
        if response.status_code != 200:
            raise CompletionError(_failure_for(response))
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage") or {}
            if not isinstance(content, str) or not content.strip():
                raise ValueError()
            return CompletionResult(
                content=content,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                cost_usd=_cost(response.headers.get("x-litellm-response-cost")),
            )
        except ValueError, KeyError, IndexError, TypeError:
            raise CompletionError(CompletionFailure.BAD_RESPONSE) from None


def _failure_for(response: httpx.Response) -> CompletionFailure:
    # LiteLLM reports an exhausted key or team budget as 400 with a budget error type.
    if response.status_code in (400, 429) and "budget" in _error_type(response):
        return CompletionFailure.BUDGET_EXCEEDED
    if response.status_code in (400, 401, 403, 404):
        return CompletionFailure.KEY_OR_MODEL_REJECTED
    return CompletionFailure.UNAVAILABLE


def _error_type(response: httpx.Response) -> str:
    try:
        error = response.json().get("error") or {}
        return f"{error.get('type', '')} {error.get('message', '')}".lower()
    except ValueError, AttributeError, json.JSONDecodeError:
        return ""


def _cost(header: str | None) -> Decimal | None:
    if not header:
        return None
    try:
        cost = Decimal(header)
    except InvalidOperation:
        return None
    return cost if cost.is_finite() and cost >= 0 else None
