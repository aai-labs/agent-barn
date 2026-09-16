"""A generic HTTP trigger: any external system can make an Agent do a named job.

Unlike every other plugin here, there is no provider on the other side -- no Slack, no
mailbox, no bot framework. The caller is whatever a user pointed at the URL: Jira
automation, a CI job, another Agent. That changes two things.

First, the instruction cannot come from the message, because a machine sends a payload,
not a request. It comes from the Connection's prompt template, written once at setup and
visible to org owners and admins. That is most of the security story too: whoever holds
the secret can fire the trigger, but cannot redirect the Agent to a different task.

Second, nobody is waiting. The delivery is admitted as an EVENT (see `execution_policy`),
which is what stops the runtime treating it like a chat turn someone will retry.
"""

import hashlib
import hmac
import json
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

# A payload is echoed back on every claim and stored in the transcript, so it is not a
# place to put a file. Generous enough for any real event, small enough to bound cost.
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_PAYLOAD_DEPTH = 12
MAX_ORDERING_KEY_LENGTH = 256
MAX_SUBJECT_LENGTH = 512

DEFAULT_PROMPT = "An event arrived. Read the payload below and do what this connection was set up to do."


class WebhookSettings(PlatformSettings):
    prompt_template: str = Field(
        default="",
        max_length=10_000,
        title="What the agent should do",
        description=(
            "The instruction the agent receives every time this webhook fires. Insert values from the event "
            "with {{ payload.field }}, using dots for nested values such as {{ payload.issue.key }}. The full "
            "event payload is always included below the instruction, so the agent sees it either way."
        ),
        json_schema_extra={"format": "textarea"},
    )
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
    auth_mode: str = Field(
        default="hmac",
        pattern="^(bearer|hmac)$",
        title="How callers authenticate",
        description=(
            "HMAC signs the request body, so a changed body is rejected even by someone holding the secret. "
            "Bearer sends the secret as an Authorization header, which is simpler when the caller cannot sign."
        ),
    )
    secret: str = Field(
        min_length=32,
        max_length=512,
        title="Shared secret",
        description=(
            "You choose this value and give the same one to the calling system. Treat it as this agent's "
            "credentials: anyone holding it can make the agent run this job."
        ),
    )


def _depth(value: Any, current: int = 1) -> int:
    if current > MAX_PAYLOAD_DEPTH:
        return current
    if isinstance(value, dict):
        return max((_depth(item, current + 1) for item in value.values()), default=current)
    if isinstance(value, list):
        return max((_depth(item, current + 1) for item in value), default=current)
    return current


def _contains_nul(value: Any) -> bool:
    """PostgreSQL's jsonb rejects a NUL inside a string, and this payload is stored as
    jsonb. Better a clear 400 to the caller than a 500 from the database."""
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(isinstance(key, str) and "\x00" in key for key in value) or any(
            _contains_nul(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_nul(item) for item in value)
    return False


def _render(template: str, payload: dict[str, Any]) -> str:
    """Substitute {{ dotted.path }} against the payload.

    Never raises. This runs after the delivery is already claimed and marked PROCESSING,
    so an exception here would strand the row until its lease expires, five times over.
    A template that refers to something absent produces an empty string, which the agent
    can see and reason about; the full payload follows regardless.

    Deliberately not str.format: a literal brace in the template would raise, and
    "{0.__class__.__init__.__globals__}" would walk straight out of the payload.
    """
    out: list[str] = []
    rest = template
    while True:
        start = rest.find("{{")
        if start == -1:
            out.append(rest)
            return "".join(out)
        end = rest.find("}}", start)
        if end == -1:
            out.append(rest)
            return "".join(out)
        out.append(rest[:start])
        out.append(_resolve(rest[start + 2 : end].strip(), payload))
        rest = rest[end + 2 :]


def _resolve(path: str, payload: dict[str, Any]) -> str:
    if not path:
        return ""
    current: Any = {"payload": payload}
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return ""
    if current is None:
        return ""
    if isinstance(current, str):
        return current
    if isinstance(current, bool | int | float):
        return json.dumps(current)
    return json.dumps(current, separators=(",", ":"), sort_keys=True)


class WebhookPlatformPlugin(PlatformPlugin):
    key = "webhook"
    display_name = "Webhook"
    setup_hint = (
        "How it works\n"
        "• Agent Barn gives this connection its own URL once you save it. Point any system that can send an "
        "HTTP request at that URL and the agent runs the instruction you wrote here.\n"
        "• The instruction is fixed at setup. A caller supplies the event, never the task, so a leaked secret "
        "cannot be used to tell the agent to do something else.\n\n"
        "Authentication\n"
        "• Pick a secret at least 32 characters long and give the same value to the calling system.\n"
        "• The secret is stored encrypted and never shown again, so keep your own copy.\n"
        "• There is no rotation yet: changing the secret takes effect immediately and any caller still using "
        "the old one starts failing.\n\n"
        "What the caller sends\n"
        "• Header " + VERSION_HEADER + ": 1, and a JSON body with event_id and payload.\n"
        "• Optional subject groups related events in the conversation view.\n"
        "• Optional ordering_key controls concurrency: two events sharing a value run one after another, "
        "different values run at the same time, and no key at all means never wait for anything.\n"
        "• The same event_id twice produces one run, so a caller that retries is safe.\n\n"
        "What to expect\n"
        "• A 202 means accepted for processing, not finished. Delivery is at-least-once, so write the agent's "
        "instruction so that running it twice on one event is harmless.\n"
        "• Events that arrive while the agent is stopped are not processed yet."
    )
    post_setup_hint = (
        "Paste the URL above into the calling system. If this agent was already running when you created "
        "this connection, restart it: a running agent only picks up webhook triggers after a restart."
    )
    capabilities = frozenset({PlatformCapability.WEBHOOK_INGRESS})
    settings_model = WebhookSettings
    credentials_model = WebhookCredentials
    # Nobody is watching a progress message, and there is no chat window to put it in.
    supports_progress_updates = False

    def validate_external(self, settings: PlatformSettings, credentials: PlatformCredentials) -> str | None:
        del settings, credentials
        # There is no provider to call. The secret is whatever the user chose, and the
        # first real request is what proves the two sides agree.
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

        if credentials.auth_mode == "bearer":
            self._verify_bearer(credentials, request)
        else:
            self._verify_signature(credentials, request)

        version = request.header(VERSION_HEADER)
        if version is None:
            raise ValueError(f"Missing {VERSION_HEADER} header. Send {VERSION_HEADER}: 1.")
        if version not in SUPPORTED_VERSIONS:
            raise ValueError(f"Unsupported webhook contract version {version!r}. Supported: 1.")

        self._verify_contract(request.payload)

    @staticmethod
    def _verify_bearer(credentials: WebhookCredentials, request: WebhookRequest) -> None:
        provided = request.authorization.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(provided, credentials.secret):
            raise PermissionError("Webhook bearer token does not match this connection's secret")

    @staticmethod
    def _verify_signature(credentials: WebhookCredentials, request: WebhookRequest) -> None:
        provided = (request.header(SIGNATURE_HEADER) or "").strip()
        if not provided:
            raise PermissionError(f"Missing {SIGNATURE_HEADER} header")
        # Signed over the bytes that arrived, not over a re-serialized parse: two
        # different byte strings can produce the same dict, and only one was signed.
        expected = "sha256=" + hmac.new(credentials.secret.encode(), request.raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(provided, expected):
            raise PermissionError("Webhook signature does not match the request body")

    @staticmethod
    def _verify_contract(payload: dict[str, Any]) -> None:
        event_id = payload.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("event_id is required and must be a non-empty string")
        if len(event_id) > 512:
            raise ValueError("event_id must be 512 characters or fewer")

        body = payload.get("payload")
        # ValueError, not TypeError: this is a malformed request from a caller, which the
        # route turns into a 400. A TypeError would surface as a 500 and read as our bug.
        if not isinstance(body, dict):
            raise ValueError("payload is required and must be a JSON object")  # noqa: TRY004
        if len(json.dumps(body).encode()) > MAX_PAYLOAD_BYTES:
            raise ValueError(f"payload must be {MAX_PAYLOAD_BYTES} bytes or fewer when encoded as JSON")
        if _depth(body) > MAX_PAYLOAD_DEPTH:
            raise ValueError(f"payload is nested more than {MAX_PAYLOAD_DEPTH} levels deep")
        if _contains_nul(body):
            raise ValueError("payload must not contain NUL characters")

        for name, limit in (("subject", MAX_SUBJECT_LENGTH), ("ordering_key", MAX_ORDERING_KEY_LENGTH)):
            value = payload.get(name)
            if value is not None and (not isinstance(value, str) or len(value) > limit):
                raise ValueError(f"{name} must be a string of {limit} characters or fewer")

        response_url = payload.get("response_url")
        if response_url is not None and not isinstance(response_url, str):
            raise ValueError("response_url must be a string")

    def normalize_inbound(self, settings: PlatformSettings, payload: dict[str, Any]) -> InboundAdmissionResult:
        del settings
        event_id = str(payload.get("event_id") or "").strip()
        body = payload.get("payload")
        if not event_id or not isinstance(body, dict):
            # verify_webhook already rejected these with a 400. Reaching here means the
            # payload came from somewhere that skipped it, so refuse rather than guess.
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)

        subject = str(payload.get("subject") or "").strip() or "events"
        metadata: dict[str, str | int | float | bool | None] = {"event_id": event_id}
        for name in ("subject", "response_url", ORDERING_KEY_METADATA):
            value = payload.get(name)
            if isinstance(value, str) and value.strip():
                metadata[name] = value.strip()

        return InboundAdmissionResult(
            CommunicationPolicyDisposition.ACCEPTED,
            (
                NormalizedCommunicationEnvelope(
                    provider_message_id=event_id,
                    occurred_at=datetime.now(UTC),
                    # EVENT is what makes this a job rather than a chat turn. The subject
                    # groups related events in the conversation view; it deliberately
                    # does not decide ordering, which is the caller's own contract.
                    location=ConversationLocation(id=subject, type="EVENT", display_name=subject),
                    text=event_id,
                    provider_metadata=metadata,
                    payload=body,
                ),
            ),
        )

    def runtime_prompt(self, settings: PlatformSettings, envelope: NormalizedCommunicationEnvelope) -> str:
        assert isinstance(settings, WebhookSettings)
        payload = envelope.payload or {}
        instruction = _render(settings.prompt_template, payload).strip() or DEFAULT_PROMPT
        subject = str(envelope.provider_metadata.get("subject") or "")
        # The payload goes in as JSON rather than prose so nothing about its shape is
        # lost. Blank lines and a fence keep it unambiguous where the event starts.
        lines = [instruction, ""]
        if subject:
            lines.append(f"Subject: {subject}")
        lines += ["Event payload:", "```json", json.dumps(payload, indent=2, sort_keys=True), "```"]
        return "\n".join(lines)

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
        # in agent_chat_message and shows in the conversation view; posting it to a
        # caller's response_url is a later change. Without this no-op every reply would
        # hit the base class's NotImplementedError, retry, and dead-letter.
        return f"webhook:{envelope.source_delivery_id}"
