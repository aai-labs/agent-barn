import re

from pydantic import Field, field_validator

from api.domains.communications.models import PlatformCapability
from api.domains.communications.plugins.base import (
    PlatformCredentials,
    PlatformPlugin,
    PlatformSettings,
)

_PHONE_DIGITS = re.compile(r"^[1-9][0-9]{6,14}$")
_GROUP_JID = re.compile(r"^[0-9]+(-[0-9]+)?@g\.us$")


class WhatsAppSettings(PlatformSettings):
    dm_policy: str = Field(
        default="allowlist",
        pattern="^(off|open|allowlist)$",
        title="Direct messages",
        description=(
            "Off ignores DMs, Open accepts DMs from anyone who has the number, Allowlist restricts to Allowed numbers."
        ),
    )
    allowed_numbers: list[str] = Field(
        default_factory=list,
        title="Allowed numbers",
        description=(
            "Phone numbers allowed to message this agent, in international format with the country code, "
            "such as +15551234567. Used when Direct messages is Allowlist."
        ),
    )
    group_policy: str = Field(
        default="off",
        pattern="^(off|open|allowlist)$",
        title="Group access",
        description=(
            "Off ignores groups, Open responds in any group the number is in, Allowlist restricts it to Allowed groups."
        ),
    )
    allowed_group_ids: list[str] = Field(
        default_factory=list,
        title="Allowed groups",
        description="Group IDs ending in @g.us, such as 120363001234567890@g.us. Used when Group access is Allowlist.",
    )
    require_mention: bool = Field(
        default=True,
        title="Require @mention",
        description="In groups, respond only when @mentioned or replied to.",
    )

    @field_validator("allowed_numbers")
    @classmethod
    def normalize_numbers(cls, values: list[str]) -> list[str]:
        """Keep digits only: both runtimes match the bare international number."""
        normalized: list[str] = []
        for value in values:
            digits = re.sub(r"[\s()+.-]", "", value)
            if not _PHONE_DIGITS.match(digits):
                raise ValueError(f"Not an international phone number with a country code: {value}")
            if digits not in normalized:
                normalized.append(digits)
        return normalized

    @field_validator("allowed_group_ids")
    @classmethod
    def require_group_jids(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            jid = value.strip()
            if not _GROUP_JID.match(jid):
                raise ValueError(f"Not a WhatsApp group ID ending in @g.us: {value}")
            if jid not in normalized:
                normalized.append(jid)
        return normalized


class WhatsAppCredentials(PlatformCredentials):
    """None: the runtime holds the linked-device session, created by scanning a QR code."""


class WhatsAppPlatformPlugin(PlatformPlugin):
    key = "whatsapp"
    display_name = "WhatsApp"
    setup_hint = (
        "## Before you connect\n\n"
        "1. Use a dedicated phone number with WhatsApp or WhatsApp Business installed. The Agent answers as that "
        "number, and anything sent to it can reach the Agent.\n"
        "2. This links the Agent as a WhatsApp Web device, not through Meta's Business API. WhatsApp may restrict "
        "numbers that send bulk or unsolicited messages, so only answer people who message first.\n\n"
        "## Link the phone\n\n"
        "1. Save the Connection, then choose **Link phone** and scan the QR code from WhatsApp → "
        "**Settings** → **Linked devices** → **Link a device**.\n"
        "2. Keep the phone online. WhatsApp unlinks devices whose phone stays offline for about two weeks; "
        "link again if that happens.\n\n"
        "## Set Connection access\n\n"
        "1. Direct messages default to Allowlist; add each number with its country code.\n"
        "2. Groups default to Off. Group IDs end in `@g.us`."
    )
    capabilities = frozenset({PlatformCapability.ATTACHMENTS, PlatformCapability.MENTIONS})
    settings_model = WhatsAppSettings
    credentials_model = WhatsAppCredentials

    def validate_external(self, settings: PlatformSettings, credentials: PlatformCredentials) -> str | None:
        # Nothing to check before pairing: the phone is linked from the running Agent.
        return None
