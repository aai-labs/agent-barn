"""The webhook plugin is the only ingress where the caller is a machine that will never
retry, never clarify, and never read a reply. These tests pin the two things that
protects: the contract is checked before anything is trusted, and rendering the agent's
instruction can never raise."""

import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from hamcrest import assert_that, contains_string, equal_to, is_, not_

from api.domains.communications.models import (
    CommunicationPolicyDisposition,
    ConversationLocation,
    OutboundCommunicationEnvelope,
    PlatformCapability,
)
from api.domains.communications.plugins.base import WebhookRequest
from api.domains.communications.plugins.webhook import (
    MAX_PAYLOAD_BYTES,
    SIGNATURE_HEADER,
    VERSION_HEADER,
    WebhookCredentials,
    WebhookPlatformPlugin,
    WebhookSettings,
)

_SECRET = "a" * 40


def _plugin() -> WebhookPlatformPlugin:
    return WebhookPlatformPlugin()


def _credentials(auth_mode: str = "hmac") -> WebhookCredentials:
    return WebhookCredentials(auth_mode=auth_mode, secret=_SECRET)


def _body(**overrides) -> dict:
    return {"event_id": "evt-1", "payload": {"issue": {"key": "PROJ-1"}}, **overrides}


def _request(body: dict | None = None, *, auth_mode: str = "hmac", version: str | None = "1", **headers):
    payload = _body() if body is None else body
    raw = json.dumps(payload).encode()
    all_headers = dict(headers)
    if version is not None:
        all_headers[VERSION_HEADER] = version
    authorization = ""
    if auth_mode == "hmac":
        all_headers.setdefault(
            SIGNATURE_HEADER,
            "sha256=" + hmac.new(_SECRET.encode(), raw, hashlib.sha256).hexdigest(),
        )
    else:
        authorization = f"Bearer {_SECRET}"
    return WebhookRequest(raw_body=raw, payload=payload, authorization=authorization, headers=all_headers)


def test_it_only_declares_webhook_ingress() -> None:
    """Declaring supervised ingress would make the supervisor try to open a session to a
    provider that does not exist."""
    plugin = _plugin()

    assert_that(plugin.capabilities, equal_to(frozenset({PlatformCapability.WEBHOOK_INGRESS})))
    assert_that(plugin.supports_progress_updates, is_(False))


def test_a_valid_signed_request_is_accepted() -> None:
    plugin = _plugin()

    plugin.verify_webhook(WebhookSettings(), _credentials(), _request())


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
        plugin.verify_webhook(WebhookSettings(), _credentials(), tampered)


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
        plugin.verify_webhook(WebhookSettings(), _credentials(), without)


def test_a_wrong_bearer_token_is_rejected() -> None:
    plugin = _plugin()
    request = _request(auth_mode="bearer")
    wrong = WebhookRequest(
        raw_body=request.raw_body,
        payload=request.payload,
        authorization="Bearer nope",
        headers=request.headers,
    )

    with pytest.raises(PermissionError):
        plugin.verify_webhook(WebhookSettings(), _credentials("bearer"), wrong)


def test_a_correct_bearer_token_is_accepted() -> None:
    plugin = _plugin()

    plugin.verify_webhook(WebhookSettings(), _credentials("bearer"), _request(auth_mode="bearer"))


def test_the_version_header_is_required_and_checked() -> None:
    """A versioned contract that never checks its version is not versioned."""
    plugin = _plugin()

    with pytest.raises(ValueError, match=VERSION_HEADER):
        plugin.verify_webhook(WebhookSettings(), _credentials(), _request(version=None))

    with pytest.raises(ValueError, match="Unsupported webhook contract version"):
        plugin.verify_webhook(WebhookSettings(), _credentials(), _request(version="99"))


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

    plugin.verify_webhook(WebhookSettings(), _credentials(), lowered)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"payload": {}}, "event_id is required"),
        ({"event_id": "  ", "payload": {}}, "event_id is required"),
        ({"event_id": "evt-1"}, "payload is required"),
        ({"event_id": "evt-1", "payload": "not an object"}, "payload is required"),
        ({"event_id": "evt-1", "payload": {}, "subject": 7}, "subject must be a string"),
        ({"event_id": "evt-1", "payload": {}, "ordering_key": "k" * 300}, "ordering_key must be a string"),
        ({"event_id": "evt-1", "payload": {}, "response_url": 7}, "response_url must be a string"),
        ({"event_id": "evt-1", "payload": {"a": "\x00"}}, "NUL characters"),
    ],
)
def test_an_unusable_request_says_why(body: dict, message: str) -> None:
    """A machine caller cannot read a 202 and guess. These are ValueErrors so the route
    answers 400 with the reason."""
    plugin = _plugin()

    with pytest.raises(ValueError, match=message):
        plugin.verify_webhook(WebhookSettings(), _credentials(), _request(body))


def test_an_oversized_payload_is_rejected() -> None:
    plugin = _plugin()
    body = _body(payload={"blob": "x" * (MAX_PAYLOAD_BYTES + 1)})

    with pytest.raises(ValueError, match="bytes or fewer"):
        plugin.verify_webhook(WebhookSettings(), _credentials(), _request(body))


def test_a_deeply_nested_payload_is_rejected() -> None:
    plugin = _plugin()
    nested: dict = {}
    current = nested
    for _ in range(25):
        current["next"] = {}
        current = current["next"]

    with pytest.raises(ValueError, match="levels deep"):
        plugin.verify_webhook(WebhookSettings(), _credentials(), _request(_body(payload=nested)))


def test_an_admitted_event_is_marked_as_one_and_keeps_its_payload() -> None:
    plugin = _plugin()
    body = _body(subject="PROJ-1", ordering_key="PROJ-1", response_url="https://hooks.example.com/x")

    result = plugin.normalize_inbound(WebhookSettings(), body)
    [envelope] = result

    assert_that(result.disposition, equal_to(CommunicationPolicyDisposition.ACCEPTED))
    # EVENT is what makes the runtime treat this as a job rather than a chat turn.
    assert_that(envelope.location.type, equal_to("EVENT"))
    assert_that(envelope.location.id, equal_to("PROJ-1"))
    # Dedupe: the same event_id twice is one delivery.
    assert_that(envelope.provider_message_id, equal_to("evt-1"))
    # Structure intact, not flattened into prose or stringified into metadata.
    assert_that(envelope.payload, equal_to({"issue": {"key": "PROJ-1"}}))
    assert_that(envelope.provider_metadata["ordering_key"], equal_to("PROJ-1"))
    assert_that(envelope.provider_metadata["response_url"], equal_to("https://hooks.example.com/x"))


def test_an_event_without_a_subject_still_has_somewhere_to_live() -> None:
    plugin = _plugin()

    [envelope] = plugin.normalize_inbound(WebhookSettings(), _body())

    assert_that(envelope.location.id, equal_to("events"))


def test_the_prompt_is_the_template_plus_the_untouched_payload() -> None:
    plugin = _plugin()
    settings = WebhookSettings(prompt_template="Write release notes for {{ payload.issue.key }}.")
    [envelope] = plugin.normalize_inbound(settings, _body(subject="PROJ-1"))

    prompt = plugin.runtime_prompt(settings, envelope)

    assert_that(prompt, contains_string("Write release notes for PROJ-1."))
    assert_that(prompt, contains_string("Subject: PROJ-1"))
    # The agent sees real JSON it can parse, whatever the template did or did not use.
    assert_that(prompt, contains_string('"key": "PROJ-1"'))


def test_a_connection_with_no_template_still_works() -> None:
    """A user who saves a connection before writing an instruction gets something
    usable, not an empty prompt."""
    plugin = _plugin()
    settings = WebhookSettings()
    [envelope] = plugin.normalize_inbound(settings, _body())

    prompt = plugin.runtime_prompt(settings, envelope)

    assert_that(prompt.strip(), not_(equal_to("")))
    assert_that(prompt, contains_string("Event payload:"))


@pytest.mark.parametrize(
    "template",
    [
        "Missing: {{ payload.nope }}",
        "Unclosed {{ payload.issue",
        "A literal { brace } and {{ payload.issue.key }}",
        "{{ }}",
        "{{ payload.__class__ }}",
        "{{ payload.issue }}",
    ],
)
def test_rendering_never_raises(template: str) -> None:
    """This runs after the delivery is already claimed and PROCESSING. An exception here
    would strand the row until its lease expired, five times over."""
    plugin = _plugin()
    settings = WebhookSettings(prompt_template=template)
    [envelope] = plugin.normalize_inbound(settings, _body())

    assert_that(plugin.runtime_prompt(settings, envelope), contains_string("Event payload:"))


def test_a_template_cannot_reach_outside_the_payload() -> None:
    """str.format would walk to __globals__ from here. The resolver only reads keys."""
    plugin = _plugin()
    settings = WebhookSettings(prompt_template="{{ payload.__class__.__init__.__globals__ }}")
    [envelope] = plugin.normalize_inbound(settings, _body())

    prompt = plugin.runtime_prompt(settings, envelope)

    assert_that(prompt, not_(contains_string("globals")))


def test_a_secret_must_be_long_enough_to_be_worth_having() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        WebhookCredentials(auth_mode="hmac", secret="short")


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
