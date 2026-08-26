import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api.domains.communications.models import (
    CommunicationPolicyDisposition,
    ConversationLocation,
    CredentialUniquenessScope,
    NormalizedCommunicationEnvelope,
    OutboundCommunicationEnvelope,
    PlatformCapability,
    PlatformDescriptorRead,
    ProcessingFeedbackStage,
)


class PlatformSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlatformCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ValidatedConnectionConfiguration:
    settings: dict[str, Any]
    credentials: dict[str, Any]
    external_identity: str | None
    credential_fingerprint: str | None
    credential_scope_key: str | None


@dataclass(frozen=True)
class InboundAdmissionContext:
    """Provider-neutral state a plugin may consult while admitting an event.

    Plugins decide provider-specific admission rules, while the callback keeps
    durable conversation ownership in Communications persistence rather than in
    a provider task's process memory.
    """

    connection_id: UUID
    thread_is_agent_owned: Callable[[ConversationLocation], bool]


@dataclass(frozen=True)
class ProcessingFeedbackContext:
    """Provider-neutral lifecycle facts for best-effort user feedback."""

    connection_id: UUID
    stage: ProcessingFeedbackStage
    location: ConversationLocation
    provider_message_id: str | None = None
    source_delivery_id: UUID | None = None


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


# Names used by callers that describe this boundary as normalization rather
# than admission. They intentionally refer to the same value object.
InboundNormalizationResult = InboundAdmissionResult
InboundDisposition = CommunicationPolicyDisposition


class PlatformPlugin(ABC):
    key: str
    display_name: str
    setup_hint: str | None = None
    schema_version: int = 1
    capabilities: frozenset[PlatformCapability] = frozenset()
    settings_model: type[PlatformSettings]
    credentials_model: type[PlatformCredentials]
    credential_uniqueness_scope: CredentialUniquenessScope = CredentialUniquenessScope.NONE

    @property
    def descriptor(self) -> PlatformDescriptorRead:
        return PlatformDescriptorRead(
            key=self.key,
            display_name=self.display_name,
            setup_hint=self.setup_hint,
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

    def send(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        envelope: OutboundCommunicationEnvelope,
    ) -> str:
        """Deliver one normalized reply and return the provider message id.

        A shipped plugin that cannot provide outbound delivery is not eligible for
        an enabled Communication Connection.
        """
        raise NotImplementedError(f"{self.key} does not implement outbound delivery")

    def normalize_inbound(
        self,
        settings: PlatformSettings,
        payload: dict[str, Any],
    ) -> InboundAdmissionResult:
        """Verify/filter a provider-decoded event and map it to protocol envelopes."""
        del settings, payload
        return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)

    def admit_inbound(
        self,
        settings: PlatformSettings,
        payload: dict[str, Any],
        *,
        context: InboundAdmissionContext,
    ) -> InboundAdmissionResult:
        """Apply provider admission policy before durable delivery acceptance.

        Most plugins only need normalization. Plugins with conversation-scoped
        policies (for example Slack thread mention gating) override this seam and
        use the supplied durable ownership callback without reaching into SQL.
        """
        del context
        return self.normalize_inbound(settings, payload)

    def enrich_inbound(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        envelopes: list[NormalizedCommunicationEnvelope],
    ) -> list[NormalizedCommunicationEnvelope]:
        """Best-effort provider lookups to fill sender/location names before persistence.

        Default no-op. Plugins override this to resolve names the provider
        payload omitted. Lookups must be cached and must never raise past this
        seam: a failure here must fall back to the envelopes as normalized
        rather than delay or reject durable message acceptance.
        """
        del settings, credentials
        return envelopes

    def processing_feedback(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        context: ProcessingFeedbackContext,
    ) -> None:
        """Publish optional provider UX for an inbound delivery lifecycle.

        The hook is deliberately outside durable delivery state transitions:
        failures here must never change whether a Communication Delivery is
        accepted, retried, or terminally completed.
        """
        del settings, credentials, context

    async def run_ingress(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        emit: Callable[[dict[str, Any]], Awaitable[None]],
        connected: Callable[[], Awaitable[None]],
    ) -> None:
        """Run one Connection's provider ingress session until cancelled.

        Socket and polling providers implement this hook. Webhook providers use
        the gateway's HTTP ingress contract instead.
        """
        raise NotImplementedError(f"{self.key} does not implement supervised ingress")

    def verify_webhook(
        self,
        credentials: PlatformCredentials,
        payload: dict[str, Any],
        authorization: str,
    ) -> None:
        """Authenticate a provider webhook before normalization."""
        raise NotImplementedError(f"{self.key} does not implement webhook ingress")
