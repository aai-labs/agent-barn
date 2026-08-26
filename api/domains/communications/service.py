import json
import secrets
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from pydantic import ValidationError

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.auth.models import CurrentUserContext
from api.domains.communications.models import (
    CommunicationConnection,
    CommunicationConnectionCreate,
    CommunicationConnectionRead,
    CommunicationConnectionUpdate,
    ConnectionObservedStatus,
    PlatformCapability,
    PlatformDescriptorRead,
)
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.repository import (
    CommunicationConnectionConflictError,
    CommunicationConnectionRepository,
)
from api.domains.rbac.catalog import PermissionKey
from api.infrastructure.crypto import decrypt_token, encrypt_token


@inject
@singleton
@dataclass
class CommunicationsService:
    config: Config
    authorization: AgentAuthorization
    repository: CommunicationConnectionRepository
    plugins: PlatformPluginRegistry

    def list_platforms(self, context: CurrentUserContext) -> list[PlatformDescriptorRead]:
        context.require_current_user_organization()
        return self.plugins.descriptors()

    def list_connections(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
    ) -> list[CommunicationConnectionRead]:
        self.authorization.require_visible(context, agent_id)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
        return [self._read(connection) for connection in self.repository.list_active_for_agent(agent_id, scope)]

    def create_connection(
        self,
        agent_id: UUID,
        data: CommunicationConnectionCreate,
        context: CurrentUserContext,
    ) -> CommunicationConnectionRead:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_SECRET_MANAGE)
        plugin = self._require_plugin(data.platform_key)
        validated = self._validate(
            plugin,
            data.settings,
            data.credentials,
            organization_id=agent.organization_id,
            agent_id=agent.id,
        )
        connection = CommunicationConnection(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            platform_key=plugin.key,
            display_name=data.display_name.strip(),
            enabled=data.enabled,
            schema_version=plugin.schema_version,
            settings=validated.settings,
            credentials_encrypted=self._encrypt_credentials(validated.credentials),
            driver_key_encrypted=encrypt_token(
                secrets.token_urlsafe(32),
                self.config.agent_token_encryption_key,
            ),
            external_identity=validated.external_identity,
            credential_fingerprint=validated.credential_fingerprint,
            credential_scope_key=validated.credential_scope_key,
            observed_status=ConnectionObservedStatus.PENDING if data.enabled else None,
        )
        try:
            return self._read(self.repository.create(connection))
        except CommunicationConnectionConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    def update_connection(
        self,
        agent_id: UUID,
        connection_id: UUID,
        data: CommunicationConnectionUpdate,
        context: CurrentUserContext,
    ) -> CommunicationConnectionRead:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        action_scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_UPDATE)
        connection = self.repository.get_active_in_scope(connection_id, agent_id, action_scope)
        if connection is None:
            self._raise_not_found(connection_id)
        assert connection is not None

        if data.credentials is not None:
            self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_SECRET_MANAGE)
        plugin = self._require_plugin(connection.platform_key)
        credentials = data.credentials or self._decrypt_credentials(plugin, connection.credentials_encrypted)
        settings = data.settings if data.settings is not None else connection.settings
        validated = self._validate(
            plugin,
            settings,
            credentials,
            organization_id=agent.organization_id,
            agent_id=agent.id,
        )
        if data.display_name is not None:
            connection.display_name = data.display_name.strip()
        if data.enabled is not None:
            connection.enabled = data.enabled
        connection.schema_version = plugin.schema_version
        connection.settings = validated.settings
        connection.credentials_encrypted = self._encrypt_credentials(validated.credentials)
        connection.external_identity = validated.external_identity
        connection.credential_fingerprint = validated.credential_fingerprint
        connection.credential_scope_key = validated.credential_scope_key
        connection.observed_status = ConnectionObservedStatus.PENDING if connection.enabled else None
        connection.last_error_code = None
        connection.last_error_message = None
        try:
            updated = self.repository.update(connection, expected_revision=data.revision)
            return self._read(updated)
        except CommunicationConnectionConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    def retire_connection(
        self,
        agent_id: UUID,
        connection_id: UUID,
        revision: int,
        context: CurrentUserContext,
    ) -> None:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_SECRET_MANAGE)
        action_scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_UPDATE)
        if self.repository.get_active_in_scope(connection_id, agent_id, action_scope) is None:
            self._raise_not_found(connection_id)
        try:
            if not self.repository.retire(connection_id, expected_revision=revision):
                self._raise_not_found(connection_id)
        except CommunicationConnectionConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    def _require_plugin(self, key: str):
        try:
            return self.plugins.require(key)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @staticmethod
    def _validate(plugin, settings, credentials, *, organization_id, agent_id):
        try:
            return plugin.validate_configuration(
                settings,
                credentials,
                organization_id=organization_id,
                agent_id=agent_id,
            )
        except (ValidationError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    def _encrypt_credentials(self, credentials: dict) -> str:
        return encrypt_token(
            json.dumps(credentials, sort_keys=True, separators=(",", ":")),
            self.config.agent_token_encryption_key,
        )

    def _decrypt_credentials(self, plugin, ciphertext: str) -> dict:
        try:
            raw = json.loads(decrypt_token(ciphertext, self.config.agent_token_encryption_key))
            return plugin.validate_stored_credentials(raw)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Stored Communication Connection credentials are invalid",
            ) from exc

    def _read(self, connection: CommunicationConnection) -> CommunicationConnectionRead:
        plugin = self.plugins.require(connection.platform_key)
        webhook_url = None
        if PlatformCapability.WEBHOOK_INGRESS in plugin.capabilities and self.config.api_external_url:
            webhook_url = f"{self.config.api_external_url.rstrip('/')}/communications/v1/webhooks/{connection.id}"
        return CommunicationConnectionRead.model_validate(connection).model_copy(update={"webhook_url": webhook_url})

    @staticmethod
    def _raise_not_found(connection_id: UUID) -> None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Communication Connection {connection_id} not found",
        )
