"""A generic HTTP trigger: any external system can make an Agent do a named job.

Unlike every other plugin here, there is no provider on the other side -- no Slack, no
mailbox, no bot framework. The caller is whatever a user pointed at the URL: Jira
automation, a CI job, another Agent. That changes two things.

First, the instruction comes from the request itself. A caller sends `prompt` -- the
job to do, with whatever data it needs folded in as text -- and that is exactly what
the Agent is asked. There is no connection-level template standing between the two:
the caller already knows what it wants done.

Second, nobody is waiting. The delivery is admitted as an EVENT (see `execution_policy`),
which is what stops the runtime treating it like a chat turn someone will retry.

The direct cost of letting the caller supply the prompt: whoever holds the signing
secret can make the Agent do anything it is capable of, not just the one job a fixed
template would have allowed. That is an accepted trade, not an oversight -- see the
AF-320 revision plan.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from api.domains.communications.execution_policy import ORDERING_KEY_METADATA
from api.domains.communications.models import (
    CommunicationPolicyDisposition,
    ConversationLocation,
    NormalizedCommunicationEnvelope,
    OutboundCommunicationEnvelope,
    PlatformCapability,
)
from api.domains.communications.plugins.base import (
    InboundAdmissionResult,
    PlatformCredentials,
    PlatformPlugin,
    PlatformSettings,
    WebhookRequest,
)

VERSION_HEADER = "X-AgentBarn-Webhook-Version"
SIGNATURE_HEADER = "X-AgentBarn-Signature"
SUPPORTED_VERSIONS = frozenset({"1"})

# The prompt is echoed back in the calls list and stored in the transcript, so it is
# not a place to put a file. Generous enough for any real instruction plus a chunk of
# pasted data, small enough to bound cost.
MAX_PROMPT_CHARS = 64_000
MAX_ORDERING_KEY_LENGTH = 256

# Every event for a connection shares this location: with no per-request identity to
# group by (see AF-320 revision plan -- `subject` was dropped), there is nothing to
# vary the channel id by, and it is not read anywhere. Per-event identity lives in the
# delivery's session_key (`event:{connection_id}:{event_id}`), which does not use this.
EVENT_LOCATION_ID = "events"

# secrets.token_urlsafe(32) is ~43 base64url characters, comfortably past this floor.
# Kept as a floor rather than a fixed length so verify_stored_credentials still accepts
# a value minted by a future, longer generator.
MIN_SECRET_LENGTH = 32


class WebhookSettings(PlatformSettings):
    response_url_allowed_hosts: list[str] = Field(
        default_factory=list,
        title="Hosts a reply may be sent to",
        description=(
            "Hostnames this connection is allowed to POST a result back to, such as hooks.example.com. A "
            "response_url with any other host is ignored. Replies are not sent yet; this is recorded now so "
            "the allowlist is a setup decision rather than something a caller chooses."
        ),
    )


class WebhookCredentials(PlatformCredentials):
    signing_secret: str = Field(
        min_length=MIN_SECRET_LENGTH,
        max_length=512,
        title="Signing secret",
        description=(
            "Generated when this connection is created and shown once. The calling system signs every "
            "request body with it; a request that arrives unsigned or wrongly signed is rejected."
        ),
    )


def _contains_nul(value: str) -> bool:
    """PostgreSQL's jsonb rejects a NUL inside a string, and the prompt is stored as
    jsonb via the envelope. Better a clear 400 to the caller than a 500 from the
    database."""
    return "\x00" in value


class WebhookPlatformPlugin(PlatformPlugin):
    key = "webhook"
    display_name = "Webhook"
    setup_hint = (
        "How it works\n"
        "• Agent Barn gives this connection its own URL and signing secret once you save it. Point any "
        "system that can send an HTTP request at that URL and the Agent runs the instruction it sends.\n"
        "• The secret is generated for you and shown once. Copy it now -- it is stored encrypted and never "
        "shown again. If you lose it, regenerate it from this connection's detail view; the URL stays the "
        "same, so only the calling system's secret needs updating.\n\n"
        "What the caller sends\n"
        "• Header " + VERSION_HEADER + ": 1, and header " + SIGNATURE_HEADER + ": sha256=<hex hmac-sha256 of "
        "the raw request body, using the signing secret as the key>.\n"
        "• A JSON body with event_id (a string identifying this specific event) and prompt (the instruction "
        "for the Agent, with any data it needs written directly into the text).\n"
        "• Optional ordering_key controls concurrency: two events sharing a value run one after another, "
        "different values run at the same time, and no key at all means never wait for anything.\n"
        "• The same event_id twice produces one run, so a caller that retries is safe.\n\n"
        "What to expect\n"
        "• A 202 means accepted for processing, not finished. Delivery is at-least-once, so write the "
        "instruction so that running it twice on one event is harmless.\n"
        "• Every call and the Agent's response to it appear in this connection's calls list.\n"
        "• Events that arrive while the Agent is stopped are not processed yet."
    )
    post_setup_hint = (
        "Paste the URL and secret above into the calling system. If this agent was already running when you "
        "created this connection, restart it: a running agent only picks up webhook triggers after a restart."
    )
    capabilities = frozenset({PlatformCapability.WEBHOOK_INGRESS})
    settings_model = WebhookSettings
    credentials_model = WebhookCredentials
    # Nobody is watching a progress message, and there is no chat window to put it in.
    supports_progress_updates = False
    # No provider account behind this platform, so an Agent may hold as many webhooks
    # as it wants -- one per calling system, each with its own URL and secret.
    allows_multiple_connections = True

    def mint_credentials(self) -> dict[str, Any]:
        return {"signing_secret": secrets.token_urlsafe(32)}

    def reveal_once(self, credentials: PlatformCredentials) -> dict[str, str]:
        assert isinstance(credentials, WebhookCredentials)
        return {"signing_secret": credentials.signing_secret}

    def validate_external(self, settings: PlatformSettings, credentials: PlatformCredentials) -> str | None:
        del settings, credentials
        # There is no provider to call. The secret is minted by us, and the first real
        # signed request is what proves the caller has a copy of it.
        return None

    def verify_webhook(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        request: WebhookRequest,
    ) -> None:
        """Authenticate the caller, then check the request is usable at all.

        Contract checks live here rather than in normalize_inbound because a machine
        caller has to be told. A rejection from normalize_inbound is a disposition, which
        the caller sees as 202 and an empty list -- indistinguishable from success.
        """
        del settings
        assert isinstance(credentials, WebhookCredentials)

        self._verify_signature(credentials, request)

        version = request.header(VERSION_HEADER)
        if version is None:
            raise ValueError(f"Missing {VERSION_HEADER} header. Send {VERSION_HEADER}: 1.")
        if version not in SUPPORTED_VERSIONS:
            raise ValueError(f"Unsupported webhook contract version {version!r}. Supported: 1.")

        self._verify_contract(request.payload)

    @staticmethod
    def _verify_signature(credentials: WebhookCredentials, request: WebhookRequest) -> None:
        provided = (request.header(SIGNATURE_HEADER) or "").strip()
        if not provided:
            raise PermissionError(f"Missing {SIGNATURE_HEADER} header")
        # Signed over the bytes that arrived, not over a re-serialized parse: two
        # different byte strings can produce the same dict, and only one was signed.
        expected = (
            "sha256=" + hmac.new(credentials.signing_secret.encode(), request.raw_body, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(provided, expected):
            raise PermissionError("Webhook signature does not match the request body")

    @staticmethod
    def _verify_contract(payload: dict[str, Any]) -> None:
        event_id = payload.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("event_id is required and must be a non-empty string")
        if len(event_id) > 512:
            raise ValueError("event_id must be 512 characters or fewer")

        prompt = payload.get("prompt")
        # ValueError, not TypeError: this is a malformed request from a caller, which the
        # route turns into a 400. A TypeError would surface as a 500 and read as our bug.
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required and must be a non-empty string")
        if len(prompt) > MAX_PROMPT_CHARS:
            raise ValueError(f"prompt must be {MAX_PROMPT_CHARS} characters or fewer")
        if _contains_nul(prompt):
            raise ValueError("prompt must not contain NUL characters")

        ordering_key = payload.get("ordering_key")
        if ordering_key is not None and (
            not isinstance(ordering_key, str) or len(ordering_key) > MAX_ORDERING_KEY_LENGTH
        ):
            raise ValueError(f"ordering_key must be a string of {MAX_ORDERING_KEY_LENGTH} characters or fewer")

        response_url = payload.get("response_url")
        if response_url is not None and not isinstance(response_url, str):
            raise ValueError("response_url must be a string")

    def normalize_inbound(self, settings: PlatformSettings, payload: dict[str, Any]) -> InboundAdmissionResult:
        del settings
        event_id = str(payload.get("event_id") or "").strip()
        prompt = payload.get("prompt")
        if not event_id or not isinstance(prompt, str) or not prompt.strip():
            # verify_webhook already rejected these with a 400. Reaching here means the
            # payload came from somewhere that skipped it, so refuse rather than guess.
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)

        metadata: dict[str, str | int | float | bool | None] = {"event_id": event_id}
        for name in ("response_url", ORDERING_KEY_METADATA):
            value = payload.get(name)
            if isinstance(value, str) and value.strip():
                metadata[name] = value.strip()

        return InboundAdmissionResult(
            CommunicationPolicyDisposition.ACCEPTED,
            (
                NormalizedCommunicationEnvelope(
                    provider_message_id=event_id,
                    occurred_at=datetime.now(UTC),
                    # EVENT is what makes this a job rather than a chat turn. All of a
                    # connection's events share one location -- see EVENT_LOCATION_ID.
                    location=ConversationLocation(id=EVENT_LOCATION_ID, type="EVENT", display_name="Events"),
                    text=prompt,
                    provider_metadata=metadata,
                ),
            ),
        )

    def send(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        envelope: OutboundCommunicationEnvelope,
        *,
        idempotency_key: str,
    ) -> str:
        del settings, credentials, idempotency_key
        # There is nothing to send back yet. The Agent's reply is already a durable row
        # in agent_chat_message and shows in this connection's calls list, and posting
        # it to a caller's response_url is a later change. Without this no-op every
        # reply would hit the base class's NotImplementedError, retry, and dead-letter.
        return f"webhook:{envelope.source_delivery_id}"
