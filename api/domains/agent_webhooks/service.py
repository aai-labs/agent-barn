import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Any, NoReturn
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.agent_webhooks.dispatch import AgentWebhookDispatcher, WebhookDispatchResult
from api.domains.agent_webhooks.models import (
    AgentWebhook,
    AgentWebhookCreate,
    AgentWebhookRead,
    AgentWebhookUpdate,
    WebhookDeliveryPlatform,
    WebhookDeliveryPlatformRead,
    WebhookInvocation,
    WebhookInvocationAccepted,
    WebhookInvocationCreate,
    WebhookInvocationRead,
)
from api.domains.agent_webhooks.repository import AgentWebhookConflictError, AgentWebhookRepository
from api.domains.agents.authorization import AgentAuthorization
from api.domains.auth.models import CurrentUserContext
from api.domains.communications.models import CommunicationConnection
from api.domains.communications.repository import CommunicationConnectionRepository
from api.domains.rbac.catalog import PermissionKey
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.shared.models import PaginatedItems, Pagination

VERSION_HEADER = "X-AgentBarn-Webhook-Version"
SIGNATURE_HEADER = "X-AgentBarn-Signature"
TIMESTAMP_HEADER = "X-AgentBarn-Timestamp"
WEBHOOK_CONTRACT_VERSION = "1"
# A signed request is only accepted this close to its timestamp, which bounds replay.
SIGNATURE_TOLERANCE_SECONDS = 300
SUPPORTED_PLATFORM_KEYS = frozenset(item.value for item in WebhookDeliveryPlatform)


def has_default_channel(connection: CommunicationConnection) -> bool:
    """Native runtimes deliver webhook results only to the Connection's configured default channel."""
    key = "default_delivery_target" if connection.platform_key == "slack" else "home_channel_id"
    return bool(connection.settings.get(key))


@inject
@singleton
@dataclass
class AgentWebhookService:
    repository: AgentWebhookRepository
    authorization: AgentAuthorization
    dispatcher: AgentWebhookDispatcher
    connections: CommunicationConnectionRepository
    config: Config

    def list_webhooks(self, agent_id: UUID, context: CurrentUserContext) -> list[AgentWebhookRead]:
        self.authorization.require_visible(context, agent_id)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
        return [self._read(item) for item in self.repository.list_active_in_scope(agent_id, scope)]

    def get_webhook(self, agent_id: UUID, webhook_id: UUID, context: CurrentUserContext) -> AgentWebhookRead:
        self.authorization.require_visible(context, agent_id)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
        webhook = self.repository.get_active_in_scope(webhook_id, agent_id, scope)
        if webhook is None:
            self._raise_not_found(webhook_id)
        return self._read(webhook)

    def list_delivery_platforms(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
    ) -> list[WebhookDeliveryPlatformRead]:
        self.authorization.require_visible(context, agent_id)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
        connections = self.connections.list_active_for_agent(agent_id, scope)
        return [
            WebhookDeliveryPlatformRead(
                key=WebhookDeliveryPlatform(item.platform_key),
                display_name=item.display_name,
            )
            for item in connections
            if self._ineligibility(item.platform_key, item) is None
        ]

    def create_webhook(
        self,
        agent_id: UUID,
        payload: AgentWebhookCreate,
        context: CurrentUserContext,
    ) -> AgentWebhookRead:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_SECRET_MANAGE)
        self._require_delivery_platform(agent_id, payload.delivery_platform.value)
        secret = secrets.token_urlsafe(32)
        webhook = AgentWebhook(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            display_name=payload.display_name.strip(),
            delivery_platform=payload.delivery_platform,
            enabled=payload.enabled,
            signing_secret_encrypted=encrypt_token(secret, self.config.agent_token_encryption_key),
        )
        try:
            return self._read(self.repository.create(webhook), signing_secret=secret)
        except AgentWebhookConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    def update_webhook(
        self,
        agent_id: UUID,
        webhook_id: UUID,
        payload: AgentWebhookUpdate,
        context: CurrentUserContext,
    ) -> AgentWebhookRead:
        self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_UPDATE)
        if self.repository.get_active_in_scope(webhook_id, agent_id, scope) is None:
            self._raise_not_found(webhook_id)
        if payload.delivery_platform is not None:
            self._require_delivery_platform(agent_id, payload.delivery_platform.value)
        try:
            updated = self.repository.update(
                webhook_id,
                expected_revision=payload.revision,
                display_name=payload.display_name.strip() if payload.display_name is not None else None,
                delivery_platform=payload.delivery_platform,
                enabled=payload.enabled,
            )
            return self._read(updated)
        except AgentWebhookConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    def rotate_secret(
        self,
        agent_id: UUID,
        webhook_id: UUID,
        revision: int,
        context: CurrentUserContext,
    ) -> AgentWebhookRead:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_SECRET_MANAGE)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_UPDATE)
        if self.repository.get_active_in_scope(webhook_id, agent_id, scope) is None:
            self._raise_not_found(webhook_id)
        secret = secrets.token_urlsafe(32)
        try:
            updated = self.repository.update(
                webhook_id,
                expected_revision=revision,
                signing_secret_encrypted=encrypt_token(secret, self.config.agent_token_encryption_key),
            )
            return self._read(updated, signing_secret=secret)
        except AgentWebhookConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    def retire_webhook(
        self,
        agent_id: UUID,
        webhook_id: UUID,
        revision: int,
        context: CurrentUserContext,
    ) -> None:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_SECRET_MANAGE)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_UPDATE)
        if self.repository.get_active_in_scope(webhook_id, agent_id, scope) is None:
            self._raise_not_found(webhook_id)
        try:
            if not self.repository.retire(webhook_id, expected_revision=revision):
                self._raise_not_found(webhook_id)
        except AgentWebhookConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    def accept_invocation(
        self,
        webhook_id: UUID,
        payload: dict[str, Any],
        *,
        raw_body: bytes,
        signature: str,
        timestamp: str,
        version: str,
    ) -> WebhookInvocationAccepted:
        webhook = self.repository.get_enabled_for_ingress(webhook_id)
        if webhook is None:
            raise PermissionError("Agent Webhook not found")
        self._verify_signature(webhook, raw_body, signature, timestamp)
        if version != WEBHOOK_CONTRACT_VERSION:
            raise ValueError(f"Unsupported webhook contract version {version!r}. Supported: 1.")
        validated = WebhookInvocationCreate.model_validate(payload)
        invocation, duplicate = self.repository.accept_invocation(
            webhook,
            external_event_id=validated.event_id,
            prompt=validated.prompt,
        )
        if not duplicate:
            invocation = self._dispatch(webhook, invocation)
        return WebhookInvocationAccepted(
            invocation_id=invocation.id,
            status=invocation.status,
            duplicate=duplicate,
        )

    def retry_invocation(
        self,
        agent_id: UUID,
        webhook_id: UUID,
        invocation_id: UUID,
        context: CurrentUserContext,
    ) -> WebhookInvocationRead:
        self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_UPDATE)
        webhook = self.repository.get_active_in_scope(webhook_id, agent_id, scope)
        if webhook is None:
            self._raise_not_found(webhook_id)
        if not webhook.enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Enable the webhook before retrying its invocations",
            )
        invocation = self.repository.prepare_retry_in_scope(invocation_id, webhook_id, agent_id, scope)
        if invocation is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only a failed or stalled webhook dispatch can be retried",
            )
        return WebhookInvocationRead.model_validate(self._dispatch(webhook, invocation))

    def list_invocations(
        self,
        agent_id: UUID,
        webhook_id: UUID,
        context: CurrentUserContext,
        pagination: Pagination,
    ) -> PaginatedItems[WebhookInvocationRead]:
        self.authorization.require_action(context, agent_id, PermissionKey.ACTIVITY_READ)
        scope = self.authorization.authorization_scope(context, PermissionKey.ACTIVITY_READ)
        if self.repository.get_active_in_scope(webhook_id, agent_id, scope) is None:
            self._raise_not_found(webhook_id)
        return self.repository.list_invocations_in_scope(webhook_id, agent_id, scope, pagination)

    def _verify_signature(self, webhook: AgentWebhook, raw_body: bytes, signature: str, timestamp: str) -> None:
        provided = signature.strip()
        if not provided:
            raise PermissionError(f"Missing {SIGNATURE_HEADER} header")
        if not timestamp.isdigit():
            raise PermissionError(f"Missing or invalid {TIMESTAMP_HEADER} header")
        secret = decrypt_token(webhook.signing_secret_encrypted, self.config.agent_token_encryption_key)
        signed = timestamp.encode() + b"." + raw_body
        expected = "sha256=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(provided, expected):
            raise PermissionError("Webhook signature does not match the request")
        if abs(time.time() - int(timestamp)) > SIGNATURE_TOLERANCE_SECONDS:
            raise PermissionError("Webhook signature timestamp is outside the accepted window")

    def _dispatch(self, webhook: AgentWebhook, invocation: WebhookInvocation) -> WebhookInvocation:
        platform_key = webhook.delivery_platform
        if self._delivery_platform_error(invocation.agent_id, platform_key) is None:
            result = self.dispatcher.dispatch(webhook, invocation)
        else:
            result = WebhookDispatchResult(
                0,
                error_code="DELIVERY_CHANNEL_UNAVAILABLE",
                error_message=f"Agent has no enabled native {platform_key} connection with a default channel",
            )
        return self.repository.record_dispatch_result(
            invocation.id,
            generation=invocation.dispatch_generation,
            attempts=result.attempts,
            native_job_id=result.native_job_id,
            error_code=result.error_code,
            error_message=result.error_message,
        )

    def _require_delivery_platform(self, agent_id: UUID, platform_key: str) -> None:
        if error := self._delivery_platform_error(agent_id, platform_key):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    def _delivery_platform_error(self, agent_id: UUID, platform_key: str) -> str | None:
        return self._ineligibility(platform_key, self.connections.get_active_by_platform_key(agent_id, platform_key))

    def _ineligibility(self, platform_key: str, connection: CommunicationConnection | None) -> str | None:
        """Why a Connection cannot receive webhook results, or None when it can."""
        if (
            platform_key not in SUPPORTED_PLATFORM_KEYS
            or platform_key not in self.config.native_platform_keys
            or connection is None
            or not connection.enabled
        ):
            return f"Agent has no enabled native {platform_key} connection"
        if not has_default_channel(connection):
            return f"The {platform_key} connection has no default channel configured"
        return None

    def _read(self, webhook: AgentWebhook, *, signing_secret: str | None = None) -> AgentWebhookRead:
        webhook_url = None
        if self.config.api_external_url:
            webhook_url = f"{self.config.api_external_url.rstrip('/')}/agent-hooks/v1/{webhook.id}"
        return AgentWebhookRead(
            id=webhook.id,
            agent_id=webhook.agent_id,
            display_name=webhook.display_name,
            delivery_platform=webhook.delivery_platform,
            enabled=webhook.enabled,
            revision=webhook.revision,
            webhook_url=webhook_url,
            signing_secret=signing_secret,
            created_at=webhook.created_at,
            updated_at=webhook.updated_at,
        )

    @staticmethod
    def _raise_not_found(webhook_id: UUID) -> NoReturn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent Webhook {webhook_id} not found",
        )
