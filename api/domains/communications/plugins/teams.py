import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import jwt
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
from api.infrastructure.http import resilient_request
from api.infrastructure.shared.cache import cached

_BOT_CONNECTOR_ISSUER = "https://api.botframework.com"
_BOT_CONNECTOR_OPENID = "https://login.botframework.com/v1/.well-known/openidconfiguration"
_OPENID_CACHE_SECONDS = 86_400


def _bot_connector_keys() -> list[dict[str, Any]]:
    def fetch() -> list[dict[str, Any]]:
        metadata = resilient_request("GET", _BOT_CONNECTOR_OPENID, label="Teams OpenID metadata")
        metadata.raise_for_status()
        keys_response = resilient_request("GET", metadata.json()["jwks_uri"], label="Teams OpenID keys")
        keys_response.raise_for_status()
        return list(keys_response.json().get("keys", []))

    return cached("teams-bot-connector-openid-keys", fetch, ttl=_OPENID_CACHE_SECONDS)


class TeamsSettings(PlatformSettings):
    tenant_id: str = Field(min_length=1, max_length=255)


class TeamsCredentials(PlatformCredentials):
    app_id: str = Field(min_length=1)
    app_password: str = Field(min_length=1)


class TeamsPlatformPlugin(PlatformPlugin):
    key = "teams"
    display_name = "Microsoft Teams"
    capabilities = frozenset(
        {
            PlatformCapability.ATTACHMENTS,
            PlatformCapability.MENTIONS,
            PlatformCapability.THREADS,
            PlatformCapability.WEBHOOK_INGRESS,
        }
    )
    settings_model = TeamsSettings
    credentials_model = TeamsCredentials
    credential_uniqueness_scope = CredentialUniquenessScope.GLOBAL

    def validate_external(self, settings: PlatformSettings, credentials: PlatformCredentials) -> str | None:
        assert isinstance(settings, TeamsSettings)
        assert isinstance(credentials, TeamsCredentials)
        return f"{settings.tenant_id} / {credentials.app_id}"

    def fingerprint_material(self, credentials: PlatformCredentials) -> str:
        assert isinstance(credentials, TeamsCredentials)
        return credentials.app_id

    def verify_webhook(
        self,
        credentials: PlatformCredentials,
        payload: dict[str, Any],
        authorization: str,
    ) -> None:
        assert isinstance(credentials, TeamsCredentials)
        if not authorization.startswith("Bearer "):
            raise PermissionError("Teams webhook is missing a bearer token")
        token = authorization.removeprefix("Bearer ").strip()
        try:
            token_header = jwt.get_unverified_header(token)
            key_data = next(key for key in _bot_connector_keys() if key.get("kid") == token_header.get("kid"))
            channel_id = str(payload.get("channelId") or "")
            endorsements = key_data.get("endorsements")
            if isinstance(endorsements, list) and channel_id not in endorsements:
                raise PermissionError("Teams webhook signing key is not endorsed for this channel")
            claims = jwt.decode(
                token,
                jwt.PyJWK.from_dict(key_data).key,
                algorithms=["RS256"],
                audience=credentials.app_id,
                issuer=_BOT_CONNECTOR_ISSUER,
                leeway=300,
                options={"require": ["exp", "iss", "aud", "serviceUrl"]},
            )
        except PermissionError:
            raise
        except (StopIteration, jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
            raise PermissionError("Teams webhook authentication failed") from exc
        if claims.get("serviceUrl") != payload.get("serviceUrl"):
            raise PermissionError("Teams webhook service URL does not match its signed claim")

    def send(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        envelope: OutboundCommunicationEnvelope,
    ) -> str:
        assert isinstance(credentials, TeamsCredentials)
        service_url = envelope.provider_metadata.get("service_url")
        if not isinstance(service_url, str) or not service_url.startswith("https://"):
            raise ValueError("Teams delivery is missing its authenticated service URL")
        token_response = resilient_request(
            "POST",
            "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            content=urlencode(
                {
                    "grant_type": "client_credentials",
                    "client_id": credentials.app_id,
                    "client_secret": credentials.app_password,
                    "scope": "https://api.botframework.com/.default",
                }
            ).encode(),
            label="Teams OAuth",
            retry_server_errors=True,
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        response = resilient_request(
            "POST",
            f"{service_url.rstrip('/')}/v3/conversations/{envelope.location.id}/activities",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            content=json.dumps({"type": "message", "text": envelope.text}).encode(),
            label="Teams send activity",
            retry_server_errors=True,
        )
        response.raise_for_status()
        message_id = response.json().get("id")
        if not message_id:
            raise RuntimeError("Teams send activity returned no message id")
        return str(message_id)

    def normalize_inbound(
        self,
        settings: PlatformSettings,
        payload: dict[str, Any],
    ) -> list[NormalizedCommunicationEnvelope]:
        if payload.get("type") != "message":
            return []
        conversation = payload.get("conversation") or {}
        sender = payload.get("from") or {}
        recipient = payload.get("recipient") or {}
        message_id = str(payload.get("id") or "")
        conversation_id = str(conversation.get("id") or "")
        if not message_id or not conversation_id:
            return []
        raw_time = payload.get("timestamp")
        occurred_at = datetime.fromisoformat(str(raw_time)) if raw_time else datetime.now(UTC)
        is_dm = bool(conversation.get("conversationType") == "personal")
        service_url = str(payload.get("serviceUrl") or "")
        return [
            NormalizedCommunicationEnvelope(
                provider_message_id=message_id,
                occurred_at=occurred_at,
                location=ConversationLocation(
                    id=conversation_id,
                    type="DM" if is_dm else "CHANNEL",
                    display_name=str(conversation.get("name") or "") or None,
                    thread_id=str(payload.get("replyToId") or message_id),
                ),
                sender=CommunicationSender(
                    id=str(sender.get("id") or "") or None,
                    display_name=str(sender.get("name") or "") or None,
                ),
                text=str(payload.get("text") or ""),
                reply_to_provider_message_id=str(payload.get("replyToId") or "") or None,
                provider_metadata={
                    "service_url": service_url,
                    "channel_id": str(payload.get("channelId") or ""),
                    "recipient_id": str(recipient.get("id") or ""),
                },
            )
        ]
