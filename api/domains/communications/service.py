import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from pydantic import ValidationError

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent
from api.domains.auth.models import CurrentUserContext
from api.domains.communications.addressing import build_local_part, compose_address
from api.domains.communications.email_address_repository import AgentEmailAddressRepository
from api.domains.communications.models import (
    AgentEmailAddress,
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
    addresses: AgentEmailAddressRepository
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
        connections = self.repository.list_active_for_agent(agent_id, scope)
        addresses = self.addresses.addresses_for([connection.id for connection in connections])
        return [self._read(connection, addresses) for connection in connections]

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
            created = self.repository.create(
                connection,
                allocate_address=self._address_allocator(plugin, agent) if self._allocates_address(plugin) else None,
            )
            return self._read(created)
        except CommunicationConnectionConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    def _allocates_address(self, plugin) -> bool:
        return PlatformCapability.MANAGED_ADDRESS in plugin.capabilities

    def _address_allocator(self, plugin, agent: Agent) -> Callable[[UUID], AgentEmailAddress]:
        del plugin
        mailbox = self.config.agent_email_mailbox.strip()
        domain = self.config.agent_email_domain.strip()

        def allocate(connection_id: UUID) -> AgentEmailAddress:
            local_part = build_local_part(agent.name)
            return AgentEmailAddress(
                organization_id=agent.organization_id,
                agent_id=agent.id,
                connection_id=connection_id,
                local_part=local_part,
                address=compose_address(mailbox, local_part, domain),
            )

        return allocate

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

    def build_app_package(
        self,
        agent_id: UUID,
        connection_id: UUID,
        context: CurrentUserContext,
    ) -> tuple[str, bytes]:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_UPDATE)
        connection = self.repository.get_active_in_scope(connection_id, agent_id, scope)
        if connection is None:
            self._raise_not_found(connection_id)
        assert connection is not None

        plugin = self._require_plugin(connection.platform_key)
        if PlatformCapability.APPLICATION_PROVISIONING not in plugin.capabilities:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{plugin.display_name} does not provide an installable app package",
            )
        try:
            return plugin.build_app_package(
                plugin.settings_model.model_validate(connection.settings),
                plugin.credentials_model.model_validate(
                    self._decrypt_credentials(plugin, connection.credentials_encrypted)
                ),
                connection_id=connection.id,
                # The package names the bot as people see it in the provider, so
                # it carries the Agent's name, not the Connection's UI label.
                display_name=agent.name,
            )
        except NotImplementedError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{plugin.display_name} does not provide an installable app package",
            ) from exc
        except (ValidationError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

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

    def _read(
        self,
        connection: CommunicationConnection,
        addresses: dict[UUID, str] | None = None,
    ) -> CommunicationConnectionRead:
        plugin = self.plugins.require(connection.platform_key)
        addressed_by_mailbox = PlatformCapability.MANAGED_ADDRESS in plugin.capabilities
        webhook_url = None
        if (
            PlatformCapability.WEBHOOK_INGRESS in plugin.capabilities
            and not addressed_by_mailbox
            and self.config.api_external_url
        ):
            webhook_url = f"{self.config.api_external_url.rstrip('/')}/communications/v1/webhooks/{connection.id}"
        managed_address = None
        if addressed_by_mailbox:
            if addresses is None:
                addresses = self.addresses.addresses_for([connection.id])
            managed_address = addresses.get(connection.id)
        return CommunicationConnectionRead.model_validate(connection).model_copy(
            update={"webhook_url": webhook_url, "managed_address": managed_address}
        )

    @staticmethod
    def _raise_not_found(connection_id: UUID) -> None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Communication Connection {connection_id} not found",
        )
