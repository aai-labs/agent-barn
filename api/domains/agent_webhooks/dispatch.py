import json
import logging
import time
from dataclasses import dataclass

import httpx
from injector import inject, singleton

from api.core.config import Config
from api.domains.agent_webhooks.models import AgentWebhook, WebhookInvocation
from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.infrastructure.crypto import decrypt_token

logger = logging.getLogger(__name__)

MAX_DISPATCH_ATTEMPTS = 3


def _listener_error(response: httpx.Response) -> str | None:
    """The private listener's own rejection reason; it never echoes prompts or secrets."""
    try:
        error = response.json().get("error")
    except AttributeError, ValueError:
        return None
    return error[:500] if isinstance(error, str) and error else None


@dataclass(frozen=True)
class WebhookDispatchResult:
    attempts: int
    native_job_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


@inject
@singleton
@dataclass
class AgentWebhookDispatcher:
    agents: AgentRepository
    config: Config

    def dispatch(self, webhook: AgentWebhook, invocation: WebhookInvocation) -> WebhookDispatchResult:
        agent = self.agents.get_by_id(invocation.agent_id)
        if agent is None or agent.deleted_at is not None:
            return WebhookDispatchResult(0, error_code="AGENT_NOT_FOUND", error_message="Agent is unavailable")
        if agent.status != AgentStatus.RUNNING or not agent.communication_key_encrypted:
            return WebhookDispatchResult(0, error_code="AGENT_NOT_RUNNING", error_message="Agent is not running")

        trigger_key = decrypt_token(agent.communication_key_encrypted, self.config.agent_token_encryption_key)
        url = self.config.agent_trigger_url.format(
            agent_id=invocation.agent_id,
            namespace=self.config.k8s_namespace,
        )
        body = json.dumps(
            {
                "invocation_id": str(invocation.id),
                "dispatch_generation": invocation.dispatch_generation,
                "prompt": invocation.prompt,
                "delivery_platform": getattr(webhook.delivery_platform, "value", webhook.delivery_platform),
            },
            separators=(",", ":"),
        ).encode()
        headers = {
            "Authorization": f"Bearer {trigger_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": f"{invocation.id}:{invocation.dispatch_generation}",
        }

        last_code = "DISPATCH_UNAVAILABLE"
        last_message = "Agent did not accept the trigger"
        for attempt in range(1, MAX_DISPATCH_ATTEMPTS + 1):
            try:
                response = httpx.request("POST", url, headers=headers, content=body, timeout=10)
            except httpx.TransportError:
                last_code = "DISPATCH_TRANSPORT_ERROR"
                last_message = "Agent trigger endpoint could not be reached"
            else:
                if response.status_code == 202:
                    try:
                        native_job_id = str(response.json()["native_job_id"])
                    except KeyError, TypeError, ValueError:
                        return WebhookDispatchResult(
                            attempt,
                            error_code="INVALID_AGENT_RESPONSE",
                            error_message="Agent accepted the trigger without a native job identifier",
                        )
                    return WebhookDispatchResult(attempt, native_job_id=native_job_id)
                last_code = "AGENT_REJECTED_TRIGGER"
                last_message = f"Agent trigger endpoint returned HTTP {response.status_code}"
                if response.status_code < 500 and response.status_code != 429:
                    return WebhookDispatchResult(
                        attempt, error_code=last_code, error_message=_listener_error(response) or last_message
                    )
            if attempt < MAX_DISPATCH_ATTEMPTS:
                time.sleep(0.25 * attempt)

        logger.warning(
            "Webhook invocation %s was not submitted after %d attempts", invocation.id, MAX_DISPATCH_ATTEMPTS
        )
        return WebhookDispatchResult(
            MAX_DISPATCH_ATTEMPTS,
            error_code=last_code,
            error_message=last_message,
        )
