from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

import pytest

from api.domains.communications.models import (
    ConversationLocation,
    OutboundCommunicationEnvelope,
    PlatformCapability,
)
from api.domains.communications.plugins.email import (
    DISPLAY_NAME_LIMIT,
    MAX_REFERENCES,
    REFERENCES_HEADER_BYTE_LIMIT,
    SUBJECT_LIMIT,
    EmailPlatformPlugin,
)
from api.infrastructure.email.client import EmailClient
from api.infrastructure.email.models import Email

AGENT_ADDRESS = "agent+tommy-4f2a@agents.agentbarn.dev"
CUSTOMER = "jane@acme.com"
CUSTOMER_MESSAGE_ID = "<abc123@acme.com>"
THREAD_ROOT = "<root-9f2@agents.agentbarn.dev>"


@dataclass
class EmailConfig:
    is_agent_email_enabled: bool = True


class RecordingEmailClient:
    def __init__(self) -> None:
        self.sent: list[Email] = []

    def send(self, email: Email) -> Email:
        self.sent.append(email)
        return email


def _plugin(client: RecordingEmailClient | None = None, **config_overrides) -> EmailPlatformPlugin:
    return EmailPlatformPlugin(
        EmailConfig(**config_overrides),
        cast(EmailClient, client or RecordingEmailClient()),
    )


def _settings(plugin: EmailPlatformPlugin, **overrides):
    return plugin.settings_model.model_validate({"sender_policy": "open", **overrides})


def _credentials(plugin: EmailPlatformPlugin):
    return plugin.credentials_model.model_validate({})


def _inbound(**overrides) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "to": AGENT_ADDRESS,
        "from": CUSTOMER,
        "from_name": "Jane Customer",
        "subject": "Question about pricing",
        "text": "What does the team plan cost?",
        "message_id": CUSTOMER_MESSAGE_ID,
        "in_reply_to": "",
        "references": [],
        "auto_submitted": "",
        "precedence": "",
        "list_id": "",
        "received_at": "2026-08-31T10:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def _outbound(text: str = "It is $20 per seat.", **metadata_overrides) -> OutboundCommunicationEnvelope:
    metadata: dict[str, Any] = {
        "message_id": CUSTOMER_MESSAGE_ID,
        "subject": "Question about pricing",
        "references": THREAD_ROOT,
        "recipient": AGENT_ADDRESS,
    }
    metadata.update(metadata_overrides)
    return OutboundCommunicationEnvelope(
        source_delivery_id=uuid4(),
        location=ConversationLocation(id=CUSTOMER, type="DM", thread_id=THREAD_ROOT),
        text=text,
        provider_metadata=metadata,
    )


def _sent(plugin: EmailPlatformPlugin, client: RecordingEmailClient, envelope) -> Email:
    plugin.send(_settings(plugin), _credentials(plugin), envelope)
    return client.sent[0]


def test_descriptor_declares_webhook_ingress_and_a_managed_address() -> None:
    capabilities = _plugin().descriptor.capabilities

    assert PlatformCapability.WEBHOOK_INGRESS in capabilities
    assert PlatformCapability.MANAGED_ADDRESS in capabilities
    assert PlatformCapability.ATTACHMENTS not in capabilities


def test_connection_is_rejected_when_the_agent_domain_is_not_configured() -> None:
    plugin = _plugin(is_agent_email_enabled=False)

    with pytest.raises(ValueError):
        plugin.validate_external(_settings(plugin), _credentials(plugin))


def test_email_takes_no_per_agent_credentials() -> None:
    plugin = _plugin()

    assert _credentials(plugin).model_dump() == {}
    assert plugin.validate_external(_settings(plugin), _credentials(plugin)) is None


def test_normalizes_an_inbound_message_into_a_dm_from_the_sender() -> None:
    plugin = _plugin()

    [envelope] = plugin.normalize_inbound(_settings(plugin), _inbound())

    assert envelope.provider_message_id == CUSTOMER_MESSAGE_ID
    assert envelope.location.id == CUSTOMER
    assert envelope.location.type == "DM"
    assert envelope.sender.id == CUSTOMER
    assert envelope.sender.display_name == "Jane Customer"
    assert envelope.provider_metadata["recipient"] == AGENT_ADDRESS


def test_addresses_are_lowercased_so_one_correspondent_is_one_conversation() -> None:
    plugin = _plugin()

    [envelope] = plugin.normalize_inbound(_settings(plugin), _inbound(**{"from": "Jane@ACME.com"}))

    assert envelope.location.id == CUSTOMER


def test_a_display_name_wrapped_address_is_reduced_to_the_address() -> None:
    plugin = _plugin()

    [envelope] = plugin.normalize_inbound(_settings(plugin), _inbound(**{"from": "Jane Customer <jane@acme.com>"}))

    assert envelope.location.id == CUSTOMER


def test_thread_anchors_on_the_references_root() -> None:
    plugin = _plugin()
    payload = _inbound(references=[THREAD_ROOT, "<cloudflare-assigned@mail>"], in_reply_to="<cloudflare@mail>")

    [envelope] = plugin.normalize_inbound(_settings(plugin), payload)

    assert envelope.location.thread_id == THREAD_ROOT


def test_thread_falls_back_to_in_reply_to_without_references() -> None:
    plugin = _plugin()

    [envelope] = plugin.normalize_inbound(_settings(plugin), _inbound(in_reply_to=THREAD_ROOT))

    assert envelope.location.thread_id == THREAD_ROOT


def test_first_message_in_a_thread_roots_on_its_own_message_id() -> None:
    plugin = _plugin()

    [envelope] = plugin.normalize_inbound(_settings(plugin), _inbound())

    assert envelope.location.thread_id == CUSTOMER_MESSAGE_ID


def test_an_overlong_message_id_is_hashed_so_it_fits_the_identity_field() -> None:
    plugin = _plugin()
    long_id = "<" + ("x" * 600) + "@acme.com>"

    [envelope] = plugin.normalize_inbound(_settings(plugin), _inbound(message_id=long_id))

    assert envelope.provider_message_id.startswith("sha256:")
    assert len(envelope.provider_message_id) <= 512
    assert envelope.provider_metadata["message_id"] == long_id


def test_hashing_an_overlong_message_id_is_stable_so_retries_stay_idempotent() -> None:
    plugin = _plugin()
    payload = _inbound(message_id="<" + ("x" * 600) + "@acme.com>")

    first = plugin.normalize_inbound(_settings(plugin), payload)[0]
    second = plugin.normalize_inbound(_settings(plugin), payload)[0]

    assert first.provider_message_id == second.provider_message_id


def test_the_agent_is_given_the_sender_and_subject_the_adapter_does_not_pass_through() -> None:
    plugin = _plugin()

    [envelope] = plugin.normalize_inbound(_settings(plugin), _inbound())

    assert "Jane Customer <jane@acme.com>" in envelope.text
    assert "Question about pricing" in envelope.text
    assert "What does the team plan cost?" in envelope.text


@pytest.mark.parametrize(
    "quoted",
    [
        "On Mon, Jan 1 2026, Tommy wrote:\n> earlier message",
        "> earlier message",
        "-----Original Message-----\nFrom: Tommy\nearlier message",
    ],
)
def test_quoted_reply_history_is_trimmed_from_the_body(quoted) -> None:
    plugin = _plugin()

    [envelope] = plugin.normalize_inbound(_settings(plugin), _inbound(text=f"Thanks, that works.\n\n{quoted}"))

    assert "Thanks, that works." in envelope.text
    assert "earlier message" not in envelope.text


def test_an_overlong_sender_display_name_is_trimmed_rather_than_dropping_the_message() -> None:
    plugin = _plugin()

    [envelope] = plugin.normalize_inbound(_settings(plugin), _inbound(from_name="Jane " * 200))

    assert envelope.sender.display_name is not None
    assert len(envelope.sender.display_name) <= DISPLAY_NAME_LIMIT
    assert envelope.location.display_name is not None
    assert len(envelope.location.display_name) <= DISPLAY_NAME_LIMIT


def test_an_overlong_subject_is_trimmed_so_the_provider_does_not_reject_the_reply() -> None:
    client = RecordingEmailClient()
    plugin = _plugin(client)

    sent = _sent(plugin, client, _outbound(subject="pricing " * 300))

    assert len(sent.subject) <= SUBJECT_LIMIT


def test_an_oversized_body_is_truncated_before_it_reaches_the_runtime() -> None:
    plugin = _plugin()

    [envelope] = plugin.normalize_inbound(_settings(plugin), _inbound(text="x" * 500_000))

    assert len(envelope.text) < 500_000


@pytest.mark.parametrize(
    "payload_overrides",
    [
        {"auto_submitted": "auto-replied"},
        {"auto_submitted": "auto-generated"},
        {"precedence": "bulk"},
        {"precedence": "list"},
        {"precedence": "junk"},
        {"list_id": "<newsletter.acme.com>"},
        {"from": "MAILER-DAEMON@acme.com"},
        {"from": "noreply@acme.com"},
        {"from": "no-reply@acme.com"},
        {"from": "postmaster@acme.com"},
        {"from": ""},
        {"message_id": ""},
        {"to": ""},
        {"from": "x" * 250 + "@acme.com"},
    ],
)
def test_automated_and_unaddressable_mail_is_rejected(payload_overrides) -> None:
    plugin = _plugin()

    assert plugin.normalize_inbound(_settings(plugin), _inbound(**payload_overrides)) == []


def test_auto_submitted_no_is_ordinary_mail_and_is_admitted() -> None:
    plugin = _plugin()

    assert len(plugin.normalize_inbound(_settings(plugin), _inbound(auto_submitted="no"))) == 1


def test_a_message_whose_reference_chain_signals_a_reply_loop_is_rejected() -> None:
    plugin = _plugin()
    payload = _inbound(references=[f"<{index}@loop>" for index in range(MAX_REFERENCES + 1)])

    assert plugin.normalize_inbound(_settings(plugin), payload) == []


def test_allowlist_admits_a_listed_address() -> None:
    plugin = _plugin()
    settings = _settings(plugin, sender_policy="allowlist", allowed_senders=[CUSTOMER])

    assert len(plugin.normalize_inbound(settings, _inbound())) == 1


def test_allowlist_admits_a_listed_domain() -> None:
    plugin = _plugin()
    settings = _settings(plugin, sender_policy="allowlist", allowed_senders=["@acme.com"])

    assert len(plugin.normalize_inbound(settings, _inbound())) == 1


def test_allowlist_matching_ignores_case() -> None:
    plugin = _plugin()
    settings = _settings(plugin, sender_policy="allowlist", allowed_senders=["@ACME.com"])

    assert len(plugin.normalize_inbound(settings, _inbound())) == 1


def test_allowlist_rejects_an_unlisted_sender() -> None:
    plugin = _plugin()
    settings = _settings(plugin, sender_policy="allowlist", allowed_senders=["@trusted.example"])

    assert plugin.normalize_inbound(settings, _inbound()) == []


def test_a_domain_entry_does_not_match_a_lookalike_suffix() -> None:
    plugin = _plugin()
    settings = _settings(plugin, sender_policy="allowlist", allowed_senders=["@me.com"])

    assert plugin.normalize_inbound(settings, _inbound()) == []


def test_the_default_settings_admit_nobody_until_an_operator_opts_in() -> None:
    plugin = _plugin()

    assert plugin.normalize_inbound(plugin.settings_model.model_validate({}), _inbound()) == []


def test_a_reply_can_only_be_addressed_to_the_inbound_sender() -> None:
    client = RecordingEmailClient()
    plugin = _plugin(client)

    assert _sent(plugin, client, _outbound()).to_email == CUSTOMER


def test_a_reply_is_sent_from_the_agents_own_address() -> None:
    client = RecordingEmailClient()
    plugin = _plugin(client)

    sent = _sent(plugin, client, _outbound())

    assert sent.from_email == AGENT_ADDRESS
    assert sent.reply_to == AGENT_ADDRESS


def test_a_reply_threads_with_in_reply_to_and_references() -> None:
    client = RecordingEmailClient()
    plugin = _plugin(client)

    sent = _sent(plugin, client, _outbound())

    assert sent.headers is not None
    assert sent.headers["In-Reply-To"] == CUSTOMER_MESSAGE_ID
    assert sent.headers["References"] == f"{THREAD_ROOT} {CUSTOMER_MESSAGE_ID}"


def test_a_reply_marks_itself_automated_so_other_responders_stay_quiet() -> None:
    client = RecordingEmailClient()
    plugin = _plugin(client)

    sent = _sent(plugin, client, _outbound())

    assert sent.headers is not None
    assert sent.headers["Auto-Submitted"] == "auto-generated"


def test_a_reply_is_plain_text_only() -> None:
    client = RecordingEmailClient()
    plugin = _plugin(client)

    sent = _sent(plugin, client, _outbound())

    assert sent.text_part == "It is $20 per seat."
    assert sent.html_part == ""


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("Question about pricing", "Re: Question about pricing"),
        ("Re: Question about pricing", "Re: Question about pricing"),
        ("RE: Question about pricing", "RE: Question about pricing"),
        ("", "Re:"),
    ],
)
def test_a_reply_subject_gains_one_re_prefix_at_most(subject, expected) -> None:
    client = RecordingEmailClient()
    plugin = _plugin(client)

    assert _sent(plugin, client, _outbound(subject=subject)).subject == expected


def test_a_long_reference_chain_is_truncated_to_the_providers_header_cap() -> None:
    client = RecordingEmailClient()
    plugin = _plugin(client)
    chain = [f"<{'p' * 60}-{index}@acme.com>" for index in range(80)]

    sent = _sent(plugin, client, _outbound(references=" ".join(chain)))

    assert sent.headers is not None
    references = sent.headers["References"]
    assert len(references.encode("utf-8")) <= REFERENCES_HEADER_BYTE_LIMIT
    assert references.startswith(chain[0])
    assert references.endswith(CUSTOMER_MESSAGE_ID)


def test_a_reply_without_the_agent_address_is_rejected_rather_than_misaddressed() -> None:
    plugin = _plugin()

    with pytest.raises(ValueError):
        plugin.send(_settings(plugin), _credentials(plugin), _outbound(recipient=""))


def test_a_reply_uses_the_configured_sender_display_name() -> None:
    client = RecordingEmailClient()
    plugin = _plugin(client)

    plugin.send(
        _settings(plugin, sender_display_name="Tommy from Acme"),
        _credentials(plugin),
        _outbound(),
    )

    assert client.sent[0].from_name == "Tommy from Acme"
