from api.domains.communications.models import OutboundCommunicationEnvelope, PlatformCapability
from api.domains.communications.plugins.base import (
    PlatformCredentials,
    PlatformPlugin,
    PlatformSettings,
)


class WebSettings(PlatformSettings):
    pass


class WebCredentials(PlatformCredentials):
    pass


class WebPlatformPlugin(PlatformPlugin):
    """Built-in chat channel backed by the dashboard, not an external provider.

    Every Agent has an always-on Connection for this platform, auto-provisioned
    on first use (see WebChatService), so a user can converse with an Agent
    before connecting any real messaging platform. There is nothing to deliver
    to externally: outbound replies are already durable rows in
    agent_chat_message the moment the Runtime posts them, and the dashboard
    reads/streams that table directly, so send() is a no-op.
    """

    key = "web"
    display_name = "Web Chat"
    setup_hint = "Built into the Agent detail page. No setup required."
    capabilities = frozenset({PlatformCapability.THREADS})
    settings_model = WebSettings
    credentials_model = WebCredentials

    def validate_external(self, settings: PlatformSettings, credentials: PlatformCredentials) -> str | None:
        return None

    def send(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        envelope: OutboundCommunicationEnvelope,
        *,
        idempotency_key: str,
    ) -> str:
        del settings, credentials, idempotency_key
        return f"web:{envelope.source_delivery_id}"
