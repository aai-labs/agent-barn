"""The webhook plugin is the only ingress where the caller is a machine that will never
retry, never clarify, and never read a reply. These tests pin the two things that
protects: the contract is checked before anything is trusted, and the caller's own
prompt reaches the runtime unchanged."""

import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from hamcrest import assert_that, equal_to, is_, not_

from api.domains.communications.models import (
    CommunicationPolicyDisposition,
    ConversationLocation,
    OutboundCommunicationEnvelope,
    PlatformCapability,
)
from api.domains.communications.plugins.base import PlatformPlugin, WebhookRequest, WebhookRequestRejected
from api.domains.communications.plugins.webhook import (
    MAX_PROMPT_CHARS,
    MIN_SECRET_LENGTH,
    SIGNATURE_HEADER,
    VERSION_HEADER,
    WebhookCredentials,
    WebhookPlatformPlugin,
    WebhookSettings,
)

_SECRET = "a" * 40


def _plugin() -> WebhookPlatformPlugin:
    return WebhookPlatformPlugin()


def _credentials() -> WebhookCredentials:
    return WebhookCredentials(signing_secret=_SECRET)


def _body(**overrides) -> dict:
    return {"event_id": "evt-1", "prompt": "Write release notes for PROJ-1.", **overrides}


def _request(body: dict | None = None, *, version: str | None = "1", **headers):
    payload = _body() if body is None else body
    raw = json.dumps(payload).encode()
    all_headers = dict(headers)
    if version is not None:
        all_headers[VERSION_HEADER] = version
    all_headers.setdefault(
        SIGNATURE_HEADER,
        "sha256=" + hmac.new(_SECRET.encode(), raw, hashlib.sha256).hexdigest(),
    )
    return WebhookRequest(raw_body=raw, payload=payload, authorization="", headers=all_headers)


def test_it_only_declares_webhook_ingress() -> None:
    """Declaring supervised ingress would make the supervisor try to open a session to a
    provider that does not exist."""
    plugin = _plugin()

    assert_that(plugin.capabilities, equal_to(frozenset({PlatformCapability.WEBHOOK_INGRESS})))
    assert_that(plugin.supports_progress_updates, is_(False))


def test_it_allows_more_than_one_connection_per_agent() -> None:
    """Unlike every other platform, webhook has no provider account behind it -- one
    Agent legitimately wants several, one per calling system."""
    plugin = _plugin()

    assert_that(plugin.allows_multiple_connections, is_(True))


def test_minting_produces_a_fresh_secret_every_time() -> None:
    plugin = _plugin()

    first = plugin.mint_credentials()
    second = plugin.mint_credentials()

    assert_that(len(first["signing_secret"]), is_(not_(0)))
    assert first["signing_secret"] != second["signing_secret"]
    assert len(first["signing_secret"]) >= MIN_SECRET_LENGTH


def test_the_minted_secret_is_revealed_once() -> None:
    plugin = _plugin()
    minted = plugin.mint_credentials()
    credentials = WebhookCredentials(**minted)

    assert_that(plugin.reveal_once(credentials), equal_to({"signing_secret": minted["signing_secret"]}))


def test_a_valid_signed_request_is_accepted() -> None:
    plugin = _plugin()

    plugin.verify_webhook(_credentials(), _request())


def test_a_body_changed_after_signing_is_rejected() -> None:
    """The whole point of HMAC over raw bytes: the signature covers what was sent."""
    plugin = _plugin()
    request = _request()
    tampered = WebhookRequest(
        raw_body=json.dumps(_body(event_id="evt-2")).encode(),
        payload=_body(event_id="evt-2"),
        authorization=request.authorization,
        headers=request.headers,
    )

    with pytest.raises(PermissionError):
        plugin.verify_webhook(_credentials(), tampered)


def test_a_missing_signature_is_rejected() -> None:
    plugin = _plugin()
    request = _request()
    without = WebhookRequest(
        raw_body=request.raw_body,
        payload=request.payload,
        authorization="",
        headers={VERSION_HEADER: "1"},
    )

    with pytest.raises(PermissionError):
        plugin.verify_webhook(_credentials(), without)


def test_the_version_header_is_required_and_checked() -> None:
    """A versioned contract that never checks its version is not versioned."""
    plugin = _plugin()

    with pytest.raises(WebhookRequestRejected, match=VERSION_HEADER):
        plugin.verify_webhook(_credentials(), _request(version=None))

    with pytest.raises(WebhookRequestRejected, match="Unsupported webhook contract version"):
        plugin.verify_webhook(_credentials(), _request(version="99"))


def test_the_version_header_is_case_insensitive() -> None:
    """HTTP header names are not case-sensitive and real clients vary."""
    plugin = _plugin()
    request = _request(version=None)
    lowered = WebhookRequest(
        raw_body=request.raw_body,
        payload=request.payload,
        authorization=request.authorization,
        headers={**request.headers, VERSION_HEADER.lower(): "1"},
    )

    plugin.verify_webhook(_credentials(), lowered)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"prompt": "do it"}, "event_id is required"),
        ({"event_id": "  ", "prompt": "do it"}, "event_id is required"),
        ({"event_id": "evt-1"}, "prompt is required"),
        ({"event_id": "evt-1", "prompt": "   "}, "prompt is required"),
        ({"event_id": "evt-1", "prompt": 7}, "prompt is required"),
        ({"event_id": "evt-1", "prompt": "x" * (MAX_PROMPT_CHARS + 1)}, "characters or fewer"),
        ({"event_id": "evt-1", "prompt": "do it", "ordering_key": "k" * 300}, "ordering_key must be a string"),
        ({"event_id": "evt-1", "prompt": "do it", "response_url": 7}, "response_url must be a string"),
        ({"event_id": "evt-1", "prompt": "has a NUL: \x00"}, "NUL characters"),
    ],
)
def test_an_unusable_request_says_why(body: dict, message: str) -> None:
    """A machine caller cannot read a 202 and guess, so the route answers 400 with the reason."""
    plugin = _plugin()

    with pytest.raises(WebhookRequestRejected, match=message):
        plugin.verify_webhook(_credentials(), _request(body))


def test_a_rejected_request_is_not_a_value_error() -> None:
    """The route returns a WebhookRequestRejected message to the caller. pydantic's
    ValidationError is a ValueError and can quote a stored secret, so the two must never be
    catchable as one another."""
    assert not issubclass(WebhookRequestRejected, ValueError)


def test_a_subject_field_is_accepted_and_simply_ignored() -> None:
    """subject was dropped from the contract -- it only ever fed the conversation view,
    which webhook events no longer appear in. A caller that still sends it (an old
    integration, a copy-pasted example) should not be broken by it."""
    plugin = _plugin()

    plugin.verify_webhook(_credentials(), _request(_body(subject="whatever")))
    [envelope] = plugin.normalize_inbound(WebhookSettings(), _body(subject="whatever"))

    assert_that(envelope.provider_metadata.get("subject"), is_(None))


def test_an_admitted_event_is_marked_as_one_and_carries_the_prompt_as_its_text() -> None:
    plugin = _plugin()
    body = _body(ordering_key="PROJ-1", response_url="https://hooks.example.com/x")

    result = plugin.normalize_inbound(WebhookSettings(), body)
    [envelope] = result

    assert_that(result.disposition, equal_to(CommunicationPolicyDisposition.ACCEPTED))
    # EVENT is what makes the runtime treat this as a job rather than a chat turn.
    assert_that(envelope.location.type, equal_to("EVENT"))
    # Dedupe: the same event_id twice is one delivery.
    assert_that(envelope.provider_message_id, equal_to("evt-1"))
    # The prompt IS the text -- no template, no separate payload object.
    assert_that(envelope.text, equal_to("Write release notes for PROJ-1."))
    assert_that(envelope.provider_metadata["ordering_key"], equal_to("PROJ-1"))
    assert_that(envelope.provider_metadata["response_url"], equal_to("https://hooks.example.com/x"))


def test_runtime_prompt_is_the_base_behaviour() -> None:
    """With no connection-level template, the base class's `return envelope.text` is
    exactly right -- webhook does not override it."""
    assert_that(WebhookPlatformPlugin.runtime_prompt, is_(PlatformPlugin.runtime_prompt))


def test_a_secret_must_be_long_enough_to_be_worth_having() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        WebhookCredentials(signing_secret="short")


def test_replying_is_a_no_op_rather_than_a_dead_letter() -> None:
    """There is no provider to send to yet. Without this the base class raises, the
    reply retries five times and the delivery dead-letters."""
    plugin = _plugin()

    delivery_id = uuid4()
    envelope = OutboundCommunicationEnvelope(
        source_delivery_id=delivery_id,
        location=ConversationLocation(id="events", type="EVENT"),
        text="the agent's answer",
    )

    assert_that(
        plugin.send(WebhookSettings(), _credentials(), envelope, idempotency_key="k"),
        equal_to(f"webhook:{delivery_id}"),
    )
