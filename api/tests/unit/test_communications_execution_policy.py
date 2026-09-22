"""The policy module is the only place a DeliveryKind is compared. These tests hold the
two invariants that make that safe: the CONVERSATION contract is unchanged, and adding a
kind cannot silently leave a call site without an answer."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from uuid import UUID

import pytest
from hamcrest import assert_that, equal_to, is_, not_

from api.domains.communications.execution_policy import (
    ORDERING_KEY_METADATA,
    kind_for_location,
    kinds_for_protocol,
    ordering_key_for,
    policy_for,
    session_key_for,
)
from api.domains.communications.models import (
    ConversationLocation,
    DeliveryKind,
    NormalizedCommunicationEnvelope,
)

_ADAPTER_PATH = Path(__file__).parents[2] / "domains" / "agents" / "scripts" / "communications-runtime-adapter.py"
_CONNECTION_ID = UUID("11111111-1111-1111-1111-111111111111")


def _load_adapter(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    for key, value in {
        "COMMUNICATIONS_URL": "http://communications.test",
        "COMMUNICATIONS_API_KEY": "communications-key",
        "AGENT_ID": "agent-1",
        "RUNTIME_API_URL": "http://runtime.test",
        "RUNTIME_API_KEY": "runtime-key",
        "RUNTIME_MODEL": "test-model",
    }.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("adapter_under_policy_test", _ADAPTER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load Communications runtime adapter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _envelope(
    *,
    location_type: str = "CHANNEL",
    location_id: str = "channel-one",
    thread_id: str | None = None,
    provider_message_id: str = "message-one",
    metadata: dict | None = None,
) -> NormalizedCommunicationEnvelope:
    return NormalizedCommunicationEnvelope(
        provider_message_id=provider_message_id,
        occurred_at=datetime.now(UTC),
        location=ConversationLocation(id=location_id, type=location_type, thread_id=thread_id),
        text="hello",
        provider_metadata=metadata or {},
    )


@pytest.mark.parametrize(
    ("location_id", "thread_id"),
    [("channel-one", None), ("channel-one", "thread-one"), ("D0123", "1700000000.1")],
)
def test_the_conversation_session_key_matches_what_the_pod_derives(
    monkeypatch: pytest.MonkeyPatch,
    location_id: str,
    thread_id: str | None,
) -> None:
    """The pod still derives this key when talking to an older server, so the two
    formulas must agree exactly. If they ever diverge a conversation silently forks
    into two runtime sessions."""
    adapter = _load_adapter(monkeypatch)
    envelope = _envelope(location_id=location_id, thread_id=thread_id)

    ours = session_key_for(_CONNECTION_ID, envelope)
    theirs = adapter.session_key_for(
        {
            "connection_id": str(_CONNECTION_ID),
            "envelope": {"location": {"id": location_id, "thread_id": thread_id}},
        }
    )

    assert_that(ours, equal_to(theirs))


def test_an_event_session_key_is_not_mistaken_for_a_conversation() -> None:
    """scripts/messaging/agentbarn_message.py resolves a scheduled job's origin by
    matching the "connection:" prefix. An event has no conversation to reply into, so it
    must not match."""
    key = session_key_for(_CONNECTION_ID, _envelope(location_type="EVENT", provider_message_id="evt-1"))

    assert_that(key.startswith("connection:"), is_(False))
    assert_that(key, equal_to(f"event:{_CONNECTION_ID}:evt-1"))


def test_two_events_never_share_a_session() -> None:
    first = session_key_for(_CONNECTION_ID, _envelope(location_type="EVENT", provider_message_id="evt-1"))
    second = session_key_for(_CONNECTION_ID, _envelope(location_type="EVENT", provider_message_id="evt-2"))

    assert_that(first, not_(equal_to(second)))


def test_a_location_type_decides_the_kind() -> None:
    assert_that(kind_for_location(ConversationLocation(id="c", type="CHANNEL")), equal_to(DeliveryKind.CONVERSATION))
    assert_that(kind_for_location(ConversationLocation(id="d", type="DM")), equal_to(DeliveryKind.CONVERSATION))
    assert_that(kind_for_location(ConversationLocation(id="e", type="EVENT")), equal_to(DeliveryKind.EVENT))


def test_events_without_an_ordering_key_never_serialise_against_anything() -> None:
    first = ordering_key_for(_CONNECTION_ID, _envelope(location_type="EVENT", provider_message_id="evt-1"))
    second = ordering_key_for(_CONNECTION_ID, _envelope(location_type="EVENT", provider_message_id="evt-2"))

    assert_that(first, not_(equal_to(second)))


def test_events_sharing_an_ordering_key_serialise_even_across_locations() -> None:
    """The caller's key is the whole contract: two events that declare the same key queue
    behind one another whatever their location."""
    shared = {ORDERING_KEY_METADATA: "PROJ-1"}
    first = ordering_key_for(
        _CONNECTION_ID,
        _envelope(location_type="EVENT", location_id="location-a", provider_message_id="evt-1", metadata=shared),
    )
    second = ordering_key_for(
        _CONNECTION_ID,
        _envelope(location_type="EVENT", location_id="location-b", provider_message_id="evt-2", metadata=shared),
    )

    assert_that(first, equal_to(second))


def test_a_blank_ordering_key_is_treated_as_absent() -> None:
    blank = ordering_key_for(
        _CONNECTION_ID,
        _envelope(location_type="EVENT", provider_message_id="evt-1", metadata={ORDERING_KEY_METADATA: "   "}),
    )

    assert_that(blank, equal_to(f"{_CONNECTION_ID}:event:evt-1"))


def test_the_conversation_ordering_key_is_unchanged() -> None:
    key = ordering_key_for(_CONNECTION_ID, _envelope(location_id="channel-one", thread_id="thread-one"))

    assert_that(key, equal_to(f"{_CONNECTION_ID}:channel-one:thread-one"))


def test_an_old_pod_is_never_handed_an_event() -> None:
    """A pod runs the adapter it was given at start, so one predating this work can
    outlive the deploy. Handing it an event would resume a session and complete-as-
    succeeded when busy -- the exact loss this epic exists to stop."""
    assert_that(kinds_for_protocol(2), equal_to(frozenset({DeliveryKind.CONVERSATION})))
    assert_that(kinds_for_protocol(3), equal_to(frozenset({DeliveryKind.CONVERSATION, DeliveryKind.EVENT})))


def test_every_kind_has_a_policy() -> None:
    """A new kind without a policy row must fail here, not at claim time in production."""
    for kind in DeliveryKind:
        assert_that(policy_for(kind).kind, equal_to(kind))
