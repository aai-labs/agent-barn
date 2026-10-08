import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from api.domains.communications.models import (
    CommunicationPolicyDisposition,
    CredentialUniquenessScope,
    NormalizedCommunicationEnvelope,
    OutboundCommunicationEnvelope,
    OutboundTargetRequest,
    PlatformCapability,
    PlatformDescriptorRead,
    ResolvedOutboundTarget,
)
from api.domains.communications.transport import platform_transport


class PlatformSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlatformCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NativeHomeDeliverySettings(BaseModel):
    """Native scheduled delivery home target, validated through Connection policy.

    This field does not authorize separate initiated sends. The schema-driven
    Connection editor and native runtime assembly use the same stored target.
    """

    default_delivery_target: OutboundTargetRequest | None = Field(
        default=None,
        title="Default delivery target",
        description="Optional destination for scheduled results. Only one Connection per Agent may set a default.",
    )


@dataclass(frozen=True)
class ValidatedConnectionConfiguration:
    settings: dict[str, Any]
    credentials: dict[str, Any]
    external_identity: str | None
    credential_fingerprint: str | None
    credential_scope_key: str | None


@dataclass(frozen=True)
class WebhookRequest:
    """One inbound provider webhook before anything trusts it.

    Carries the raw bytes because a signature covers what was sent, and re-serializing
    the parsed body does not reproduce them.
    """

    raw_body: bytes
    payload: dict[str, Any]
    authorization: str
    headers: Mapping[str, str]

    def header(self, name: str) -> str | None:
        """Case-insensitive lookup, since HTTP header names are not case-sensitive."""
        lowered = name.lower()
        return next((value for key, value in self.headers.items() if key.lower() == lowered), None)


@dataclass(frozen=True)
class InboundAdmissionResult(Sequence[NormalizedCommunicationEnvelope]):
    """Typed provider admission outcome with list-compatible envelopes.

    The sequence behavior keeps existing plugin integrations source-compatible
    while making an ignored or denied payload observable to the gateway and
    diagnostics instead of silently returning an empty list.
    """

    disposition: CommunicationPolicyDisposition
    envelopes: tuple[NormalizedCommunicationEnvelope, ...] = ()

    def __iter__(self):
        return iter(self.envelopes)

    def __len__(self) -> int:
        return len(self.envelopes)

    def __getitem__(self, index):
        return self.envelopes[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, InboundAdmissionResult):
            return self.disposition == other.disposition and self.envelopes == other.envelopes
        if isinstance(other, Sequence):
            return list(self.envelopes) == list(other)
        return NotImplemented


class PlatformPlugin(ABC):
    key: str
    display_name: str
    setup_hint: str | None = None
    post_setup_hint: str | None = None
    schema_version: int = 1
    capabilities: frozenset[PlatformCapability] = frozenset()
    settings_model: type[PlatformSettings]
    credentials_model: type[PlatformCredentials]
    credential_uniqueness_scope: CredentialUniquenessScope = CredentialUniquenessScope.NONE

    def resolve_outbound_target(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        request: OutboundTargetRequest,
    ) -> ResolvedOutboundTarget:
        raise NotImplementedError("This platform does not support native scheduled home delivery")

    def validate_outbound_target(self, settings: PlatformSettings, target: ResolvedOutboundTarget) -> None:
        raise NotImplementedError("This platform does not support native scheduled home delivery")

    @property
    def descriptor(self) -> PlatformDescriptorRead:
        return PlatformDescriptorRead(
            key=self.key,
            transport=platform_transport(self.key),
            display_name=self.display_name,
            setup_hint=self.setup_hint,
            post_setup_hint=self.post_setup_hint,
            schema_version=self.schema_version,
            capabilities=sorted(self.capabilities, key=lambda item: item.value),
            settings_schema=self.settings_model.model_json_schema(),
            credentials_schema=self.credentials_model.model_json_schema(),
        )

    def validate_configuration(
        self,
        raw_settings: dict[str, Any],
        raw_credentials: dict[str, Any],
        *,
        organization_id: UUID,
        agent_id: UUID,
    ) -> ValidatedConnectionConfiguration:
        settings = self.settings_model.model_validate(raw_settings)
        credentials = self.credentials_model.model_validate(raw_credentials)
        external_identity = self.validate_external(settings, credentials)
        if isinstance(settings, NativeHomeDeliverySettings) and settings.default_delivery_target is not None:
            self.resolve_outbound_target(settings, credentials, settings.default_delivery_target)
        fingerprint = self.credential_fingerprint(credentials)
        return ValidatedConnectionConfiguration(
            settings=settings.model_dump(mode="json"),
            credentials=credentials.model_dump(mode="json"),
            external_identity=external_identity,
            credential_fingerprint=fingerprint,
            credential_scope_key=self._scope_key(organization_id, agent_id) if fingerprint else None,
        )

    def validate_stored_settings(self, raw_settings: dict[str, Any]) -> dict[str, Any]:
        return self.settings_model.model_validate(raw_settings).model_dump(mode="json")

    def validate_stored_credentials(self, raw_credentials: dict[str, Any]) -> dict[str, Any]:
        return self.credentials_model.model_validate(raw_credentials).model_dump(mode="json")

    def credential_fingerprint(self, credentials: PlatformCredentials) -> str | None:
        if self.credential_uniqueness_scope == CredentialUniquenessScope.NONE:
            return None
        identity = self.fingerprint_material(credentials)
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def fingerprint_material(self, credentials: PlatformCredentials) -> str:
        return json.dumps(credentials.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def _scope_key(self, organization_id: UUID, agent_id: UUID) -> str | None:
        if self.credential_uniqueness_scope == CredentialUniquenessScope.NONE:
            return None
        if self.credential_uniqueness_scope == CredentialUniquenessScope.AGENT:
            return f"agent:{agent_id}"
        if self.credential_uniqueness_scope == CredentialUniquenessScope.ORGANIZATION:
            return f"organization:{organization_id}"
        return "global"

    @abstractmethod
    def validate_external(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
    ) -> str | None:
        """Validate credentials with the provider and return a safe external identity."""

    def list_directory_entries(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        *,
        kind: str,
        search: str | None = None,
        guild_id: str | None = None,
    ) -> list[dict[str, str | None]]:
        """List safe provider-owned candidates for Connection settings.

        A platform advertises DIRECTORY_DISCOVERY only when it implements this
        seam. Returned values are display-only identifiers; credentials and
        provider payloads never leave the plugin boundary.
        """
        del settings, credentials, kind, search, guild_id
        raise NotImplementedError(f"{self.key} does not implement directory discovery")

    def verify_webhook(self, credentials: PlatformCredentials, request: WebhookRequest) -> None:
        """Authenticate a provider webhook before normalization; raise PermissionError to reject it."""
        raise NotImplementedError(f"{self.key} does not implement webhook ingress")

    def build_app_package(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        *,
        connection_id: UUID,
        display_name: str,
    ) -> tuple[str, bytes]:
        """Build an installable provider app package for this Connection.

        Platforms that require an operator to upload an application bundle
        implement this seam and declare APPLICATION_PROVISIONING. Returns the
        suggested filename and the package bytes. The package must never carry
        credential material.
        """
        raise NotImplementedError(f"{self.key} does not implement application provisioning")

    def build_install_link(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
    ) -> str:
        """Build the provider install URL that adds this Connection's bot to a server.

        Platforms whose bot is installed through a generated provider URL
        implement this seam and declare INSTALL_LINK. The returned URL must
        carry only non-secret material (client id, scopes, permissions).
        """
        raise NotImplementedError(f"{self.key} does not implement bot install links")


class GatewayDeliveryPlugin(PlatformPlugin):
    """Web Chat/Email durable replies and runtime prompt/progress behavior."""

    supports_progress_updates: bool = True

    def runtime_prompt(self, envelope: NormalizedCommunicationEnvelope) -> str:
        return envelope.text

    @abstractmethod
    def send(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        envelope: OutboundCommunicationEnvelope,
        *,
        idempotency_key: str,
    ) -> str:
        """Deliver a reply using the durable Delivery's stable idempotency key."""

    def normalize_inbound(
        self,
        settings: PlatformSettings,
        payload: dict[str, Any],
    ) -> InboundAdmissionResult:
        """Normalize and apply policy to a gateway-owned inbound payload."""
        del settings, payload
        return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
