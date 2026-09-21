"""How one delivery is executed, decided once per kind and read as data everywhere else.

Nothing outside this module compares a `DeliveryKind`: call sites take a policy and read a
field. A third kind is one row in `_POLICIES`, not a new branch in the repository, gateway,
route and pod adapter.
"""

from dataclasses import dataclass
from uuid import UUID

from api.domains.communications.models import (
    ConversationLocation,
    DeliveryKind,
    NormalizedCommunicationEnvelope,
    RuntimeExecutionRead,
)

# Where an event's caller-declared ordering key is kept in provider_metadata.
ORDERING_KEY_METADATA = "ordering_key"

_BUSY_NOTICE = "I'm still working on your previous message. Please try again shortly."


@dataclass(frozen=True)
class ExecutionPolicy:
    """What one kind of delivery expects. Plain data: no callables, no behaviour."""

    kind: DeliveryKind
    # An old pod keeps its old adapter until restarted, so claims are filtered on the
    # protocol version the pod negotiated.
    min_runtime_protocol_version: int
    resume_session: bool
    approvals_enabled: bool
    progress_updates: bool
    # None means say nothing when the agent is busy: nobody is reading an event.
    busy_notice: str | None
    # Requeue a delivery that could not run instead of completing it.
    busy_releases: bool


_CONVERSATION = ExecutionPolicy(
    kind=DeliveryKind.CONVERSATION,
    min_runtime_protocol_version=1,
    resume_session=True,
    approvals_enabled=True,
    progress_updates=True,
    busy_notice=_BUSY_NOTICE,
    busy_releases=False,
)

_EVENT = ExecutionPolicy(
    kind=DeliveryKind.EVENT,
    min_runtime_protocol_version=3,
    resume_session=False,  # each event is a discrete job
    approvals_enabled=False,  # a machine cannot answer, and the run would park until the lease expires
    progress_updates=False,
    busy_notice=None,
    busy_releases=True,
)

_POLICIES: dict[DeliveryKind, ExecutionPolicy] = {policy.kind: policy for policy in (_CONVERSATION, _EVENT)}

# Anything not listed is a conversation, so every existing plugin is untouched.
_KIND_BY_LOCATION_TYPE: dict[str, DeliveryKind] = {"EVENT": DeliveryKind.EVENT}


def kind_for_location(location: ConversationLocation) -> DeliveryKind:
    """Derived from the location, not declared by the plugin: `web_chat.service` admits
    envelopes straight into the delivery repository, bypassing plugin admission."""
    return _KIND_BY_LOCATION_TYPE.get(location.type, DeliveryKind.CONVERSATION)


def policy_for(kind: DeliveryKind) -> ExecutionPolicy:
    return _POLICIES[kind]


def kinds_for_protocol(version: int) -> frozenset[DeliveryKind]:
    """Which kinds a pod speaking this protocol version may be handed."""
    return frozenset(policy.kind for policy in _POLICIES.values() if version >= policy.min_runtime_protocol_version)


def conversation_ordering_key(connection_id: UUID, location: ConversationLocation) -> str:
    """One in-flight turn per thread. The formula predates this module; it is unchanged."""
    return f"{connection_id}:{location.id}:{location.thread_id or 'root'}"


def _conversation_session_key(connection_id: UUID, envelope: NormalizedCommunicationEnvelope) -> str:
    # Must stay byte-identical to the adapter's `session_key_for` and to the format
    # `scripts/messaging/agentbarn_message.py` parses. Changing it orphans live sessions.
    return f"connection:{conversation_ordering_key(connection_id, envelope.location)}"


def _event_session_key(connection_id: UUID, envelope: NormalizedCommunicationEnvelope) -> str:
    # Not "connection:"-prefixed, so origin resolution finds no conversation to reply into.
    # Fresh per event, stable across attempts.
    return f"event:{connection_id}:{envelope.provider_message_id}"


def _event_ordering_key(connection_id: UUID, envelope: NormalizedCommunicationEnvelope) -> str:
    # Same key serialises, different keys run at once. Absent means unique, never a shared
    # constant, or callers who omit it would serialise behind each other.
    declared = str(envelope.provider_metadata.get(ORDERING_KEY_METADATA) or "").strip()
    if declared:
        return f"{connection_id}:order:{declared}"
    return f"{connection_id}:event:{envelope.provider_message_id}"


_SESSION_KEYS = {
    DeliveryKind.CONVERSATION: _conversation_session_key,
    DeliveryKind.EVENT: _event_session_key,
}

_ORDERING_KEYS = {
    DeliveryKind.CONVERSATION: lambda connection_id, envelope: conversation_ordering_key(
        connection_id, envelope.location
    ),
    DeliveryKind.EVENT: _event_ordering_key,
}


def session_key_for(connection_id: UUID, envelope: NormalizedCommunicationEnvelope) -> str:
    """The runtime session this delivery runs in."""
    return _SESSION_KEYS[kind_for_location(envelope.location)](connection_id, envelope)


def ordering_key_for(connection_id: UUID, envelope: NormalizedCommunicationEnvelope) -> str:
    """What this delivery serialises against while it is in flight."""
    return _ORDERING_KEYS[kind_for_location(envelope.location)](connection_id, envelope)


def runtime_execution(kind: DeliveryKind | str, session_key: str) -> RuntimeExecutionRead:
    """Flatten a policy into the block the pod is handed; the pod never sees a kind."""
    policy = policy_for(DeliveryKind(kind))
    return RuntimeExecutionRead(
        session_key=session_key,
        resume_session=policy.resume_session,
        approvals_enabled=policy.approvals_enabled,
        busy_notice=policy.busy_notice,
        busy_releases=policy.busy_releases,
    )
