import hashlib
import re
from datetime import UTC, datetime
from email.utils import parseaddr
from typing import Any, Protocol

from pydantic import Field

from api.domains.communications.models import (
    CommunicationSender,
    ConversationLocation,
    CredentialUniquenessScope,
    NormalizedCommunicationEnvelope,
    OutboundCommunicationEnvelope,
    PlatformCapability,
)
from api.domains.communications.plugins.base import (
    PlatformCredentials,
    PlatformPlugin,
    PlatformSettings,
)
from api.infrastructure.email.client import EmailClient
from api.infrastructure.email.models import Email

IDENTITY_LENGTH_LIMIT = 512
ADDRESS_LIMIT = 254
DISPLAY_NAME_LIMIT = 255
SUBJECT_LIMIT = 998
REFERENCES_HEADER_BYTE_LIMIT = 2048
MAX_REFERENCES = 100
MAX_BODY_CHARS = 100_000
UNATTENDED_LOCAL_PARTS = frozenset({"mailer-daemon", "postmaster", "no-reply", "noreply", "donotreply"})
BULK_PRECEDENCE = frozenset({"bulk", "list", "junk"})
QUOTED_HISTORY_PATTERNS = (
    re.compile(r"^>"),
    re.compile(r"^On\b.*\bwrote:\s*$"),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE),
    re.compile(r"^_{10,}\s*$"),
)
REPLY_PREFIX = re.compile(r"^re:\s", re.IGNORECASE)


class EmailValidationConfig(Protocol):
    @property
    def is_agent_email_enabled(self) -> bool: ...


class EmailSettings(PlatformSettings):
    sender_policy: str = Field(
        default="allowlist",
        pattern="^(open|allowlist)$",
        title="Who may email this agent",
        description=(
            "Allowlist accepts only the senders below. Open accepts mail from anyone who knows the address; "
            "the agent replies only to whoever wrote to it either way."
        ),
    )
    allowed_senders: list[str] = Field(
        default_factory=list,
        title="Allowed senders",
        description=(
            "Full addresses such as jane@acme.com, or a whole domain written as @acme.com. Used when Who may "
            "email this agent is Allowlist."
        ),
    )
    sender_display_name: str = Field(
        default="",
        max_length=255,
        title="Sender display name",
        description="The name recipients see next to the agent's address. Defaults to the platform sender name.",
    )


class EmailCredentials(PlatformCredentials):
    pass


class EmailPlatformPlugin(PlatformPlugin):
    key = "email"
    display_name = "Email"
    setup_hint = (
        "Address\n"
        "• Agent Barn allocates this agent its own address when the connection is created and shows it below. "
        "Hand that address to the people who should be able to reach the agent.\n"
        "• The address is never published by Agent Barn, and it is not reused if this connection is retired.\n\n"
        "Who may email this agent\n"
        "• Allowed senders starts empty, so nothing is accepted until you add an address or a domain.\n"
        "• A domain entry such as @acme.com trusts that domain's own DMARC policy. Mail failing DMARC is "
        "rejected before it reaches Agent Barn, but a domain with a weak policy is easier to spoof, so prefer "
        "full addresses where it matters.\n\n"
        "What the agent can do\n"
        "• The agent can only reply to someone who wrote to it first. It cannot start a conversation or add "
        "another recipient.\n"
        "• Replies are plain text. Attachments are not sent or received."
    )
    capabilities = frozenset(
        {
            PlatformCapability.WEBHOOK_INGRESS,
            PlatformCapability.MANAGED_ADDRESS,
            PlatformCapability.THREADS,
        }
    )
    settings_model = EmailSettings
    credentials_model = EmailCredentials
    credential_uniqueness_scope = CredentialUniquenessScope.NONE

    def __init__(self, config: EmailValidationConfig, client: EmailClient) -> None:
        self._config = config
        self._client = client

    def validate_external(self, settings: PlatformSettings, credentials: PlatformCredentials) -> str | None:
        del settings, credentials
        if not self._config.is_agent_email_enabled:
            raise ValueError(
                "Email is not configured for this environment. AGENT_EMAIL_DOMAIN and EMAIL_INBOUND_SECRET "
                "must be set alongside the Cloudflare sending credentials."
            )
        return None

    def normalize_inbound(
        self,
        settings: PlatformSettings,
        payload: dict[str, Any],
    ) -> list[NormalizedCommunicationEnvelope]:
        assert isinstance(settings, EmailSettings)
        sender = _address(payload.get("from"))
        recipient = _address(payload.get("to"))
        message_id = str(payload.get("message_id") or "").strip()
        if not sender or not recipient or not message_id:
            return []
        if len(sender) > ADDRESS_LIMIT or len(recipient) > ADDRESS_LIMIT:
            return []
        if _is_unattended(payload, sender):
            return []

        references = _reference_chain(payload)
        if len(references) > MAX_REFERENCES:
            return []
        if not _sender_admitted(settings, sender):
            return []

        subject = str(payload.get("subject") or "").strip()[:SUBJECT_LIMIT]
        sender_name = str(payload.get("from_name") or "").strip()[:DISPLAY_NAME_LIMIT] or None
        thread_id = references[0] if references else (str(payload.get("in_reply_to") or "").strip() or message_id)

        return [
            NormalizedCommunicationEnvelope(
                provider_message_id=_bounded_identity(message_id),
                occurred_at=_occurred_at(payload.get("received_at")),
                location=ConversationLocation(
                    id=sender,
                    type="DM",
                    display_name=(sender_name or sender)[:DISPLAY_NAME_LIMIT],
                    thread_id=_bounded_identity(thread_id),
                ),
                sender=CommunicationSender(id=sender, display_name=sender_name),
                text=_readable_message(sender, sender_name, subject, str(payload.get("text") or "")),
                provider_metadata={
                    "message_id": message_id,
                    "subject": subject,
                    "references": " ".join(references),
                    "recipient": recipient,
                },
            )
        ]

    def send(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        envelope: OutboundCommunicationEnvelope,
    ) -> str:
        assert isinstance(settings, EmailSettings)
        del credentials
        metadata = envelope.provider_metadata
        agent_address = str(metadata.get("recipient") or "")
        if not agent_address:
            raise ValueError("Email reply is missing the agent address captured from its inbound message")

        parent_message_id = str(metadata.get("message_id") or "")
        headers = {"Auto-Submitted": "auto-generated"}
        if parent_message_id:
            headers["In-Reply-To"] = parent_message_id
        references = _outbound_references(str(metadata.get("references") or ""), parent_message_id)
        if references:
            headers["References"] = references

        email = Email(
            to_email=envelope.location.id,
            subject=_reply_subject(str(metadata.get("subject") or "")),
            html_part="",
            text_part=envelope.text,
            from_name=settings.sender_display_name or None,
            from_email=agent_address,
            reply_to=agent_address,
            headers=headers,
        )
        self._client.send(email)
        return f"outbound:{envelope.source_delivery_id}"


def _address(raw: Any) -> str:
    _, address = parseaddr(str(raw or ""))
    return address.strip().lower()


def _bounded_identity(value: str) -> str:
    if len(value) <= IDENTITY_LENGTH_LIMIT:
        return value
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _reference_chain(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("references")
    if isinstance(raw, str):
        raw = raw.split()
    if not isinstance(raw, list):
        return []
    return [entry for entry in (str(item).strip() for item in raw) if entry]


def _is_unattended(payload: dict[str, Any], sender: str) -> bool:
    auto_submitted = str(payload.get("auto_submitted") or "").strip().lower()
    if auto_submitted and auto_submitted != "no":
        return True
    if str(payload.get("precedence") or "").strip().lower() in BULK_PRECEDENCE:
        return True
    if str(payload.get("list_id") or "").strip():
        return True
    return sender.split("@", 1)[0] in UNATTENDED_LOCAL_PARTS


def _sender_admitted(settings: EmailSettings, sender: str) -> bool:
    if settings.sender_policy == "open":
        return True
    domain = sender.split("@", 1)[-1]
    for raw_entry in settings.allowed_senders:
        entry = raw_entry.strip().lower()
        if not entry:
            continue
        if entry.startswith("@"):
            if domain == entry[1:]:
                return True
        elif entry == sender:
            return True
    return False


def _occurred_at(raw: Any) -> datetime:
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw).astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _readable_message(sender: str, sender_name: str | None, subject: str, body: str) -> str:
    origin = f"{sender_name} <{sender}>" if sender_name else sender
    return f"From: {origin}\nSubject: {subject}\n\n{_without_quoted_history(body)}"


def _without_quoted_history(body: str) -> str:
    kept: list[str] = []
    for line in body.replace("\r\n", "\n").split("\n"):
        if any(pattern.match(line.strip()) for pattern in QUOTED_HISTORY_PATTERNS):
            break
        kept.append(line)
    return "\n".join(kept).strip()[:MAX_BODY_CHARS]


def _reply_subject(subject: str) -> str:
    if not subject:
        return "Re:"
    replied = subject if REPLY_PREFIX.match(subject) else f"Re: {subject}"
    return replied[:SUBJECT_LIMIT]


def _outbound_references(stored: str, parent_message_id: str) -> str:
    chain = [entry for entry in stored.split() if entry]
    if parent_message_id and parent_message_id not in chain:
        chain.append(parent_message_id)
    if not chain:
        return ""

    while len(" ".join(chain).encode("utf-8")) > REFERENCES_HEADER_BYTE_LIMIT and len(chain) > 2:
        del chain[1]
    return " ".join(chain)
