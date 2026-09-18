"""How one delivery is executed, decided once per kind and read as data everywhere else.

The seam between a chat turn and a machine event is not about origin -- Teams-vs-Jira is
origin, conversation-vs-job is contract, and the two are independent. So the contract
rides on the delivery, and this module is the only place that knows what each contract
means.

**Nothing outside this module compares a `DeliveryKind`.** Call sites take a policy and
read a field. That rule is the whole point: a `kind` with `if kind == EVENT` spread over a
dozen files is worse than no kind at all, because then the difference is everywhere and
nowhere. A third kind must be one row in `_POLICIES`, not a new branch in the repository,
the gateway, the route and the pod adapter.

The dataclass therefore holds plain data only. Anything that needs arguments is a module
function dispatching through a dict keyed by kind.
"""

from dataclasses import dataclass
from uuid import UUID

from api.domains.communications.models import (
    ConversationLocation,
    DeliveryKind,
    NormalizedCommunicationEnvelope,
    RuntimeExecutionRead,
)

# How an event declares its concurrency contract. The plugin parses the caller's request
# into this key; the ordering builder below reads it back out. One definition, two users.
ORDERING_KEY_METADATA = "ordering_key"

_BUSY_NOTICE = "I'm still working on your previous message. Please try again shortly."


@dataclass(frozen=True)
class ExecutionPolicy:
    """What one kind of delivery expects. Plain data: no callables, no behaviour."""

    kind: DeliveryKind
    # A pod runs the adapter it was given when it started, so an old pod can outlive this
    # deploy indefinitely. Claims are filtered on the version the pod negotiated.
    min_runtime_protocol_version: int
    resume_session: bool
    approvals_enabled: bool
    progress_updates: bool
    # What to tell the sender when the agent is already busy. None means say nothing:
    # there is no one reading, and a chat line in an event's transcript is noise.
    busy_notice: str | None
    # Whether a delivery that could not run goes back on the queue instead of being
    # completed. Completing work that did not happen is the bug this epic exists to fix.
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
    # Each event is a discrete job. Resuming would pile unrelated work into one
    # ever-growing context and let yesterday's event colour today's answer.
    resume_session=False,
    # A machine cannot answer a question. Asking one parks the run until the lease
    # expires, so events run with approvals off and fail instead of hanging.
    approvals_enabled=False,
    progress_updates=False,
    busy_notice=None,
    busy_releases=True,
)

_POLICIES: dict[DeliveryKind, ExecutionPolicy] = {policy.kind: policy for policy in (_CONVERSATION, _EVENT)}

# The one place a location type becomes a kind. Anything not listed is a conversation,
# which keeps every existing plugin and the direct web-chat path working untouched.
_KIND_BY_LOCATION_TYPE: dict[str, DeliveryKind] = {"EVENT": DeliveryKind.EVENT}


def kind_for_location(location: ConversationLocation) -> DeliveryKind:
    """Read the contract off the envelope.

    Derived from the location rather than declared by the plugin because
    `web_chat.service` admits envelopes straight into the delivery repository, bypassing
    plugin admission. One fact, every path.
    """
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
    # Byte-identical to the adapter's own `session_key_for`, and to the format
    # `scripts/messaging/agentbarn_message.py` parses to find a scheduled job's origin
    # conversation. Changing this string orphans every live runtime session.
    return f"connection:{conversation_ordering_key(connection_id, envelope.location)}"


def _event_session_key(connection_id: UUID, envelope: NormalizedCommunicationEnvelope) -> str:
    # Deliberately not "connection:"-prefixed: an event has no conversation to reply into,
    # so origin resolution should find none. Keyed on the event id, which the contract
    # requires and dedupes on, so it is fresh per event and stable across attempts.
    return f"event:{connection_id}:{envelope.provider_message_id}"


def _event_ordering_key(connection_id: UUID, envelope: NormalizedCommunicationEnvelope) -> str:
    # Ordering is a caller contract: same key serialises, different keys run at once.
    # Absent means unique -- never a shared constant, or every caller who skipped the
    # docs gets silently serialised behind strangers.
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
    """Flatten a policy into the block the pod is handed.

    The pod reads fields; it does not know what a kind is. That keeps the contract in
    one place and lets an older pod fall back to its own defaults field by field.
    """
    policy = policy_for(DeliveryKind(kind))
    return RuntimeExecutionRead(
        session_key=session_key,
        resume_session=policy.resume_session,
        approvals_enabled=policy.approvals_enabled,
        busy_notice=policy.busy_notice,
        busy_releases=policy.busy_releases,
    )
