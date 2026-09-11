"""Release A of the approval field: the models accept it, nothing writes it yet.

Outbound envelopes are persisted as JSONB and re-validated on every retry, and
`OutboundCommunicationEnvelope` forbids extras. So the release that can *read*
the field has to be everywhere before the release that writes it -- otherwise an
older replica mid-rollout rejects the envelope, exhausts its retries, and
dead-letters a row that then blocks its whole ordering key.
"""

from uuid import uuid4

import pytest
from pydantic import ConfigDict, ValidationError

from api.domains.communications.models import (
    ApprovalRequest,
    ConversationLocation,
    OutboundCommunicationEnvelope,
    PlatformCapability,
    RuntimeReplyCreate,
)

_APPROVAL = {"run_id": "run-1", "command": "rm -rf build", "choices": ["once", "deny"]}


def _envelope(**overrides) -> OutboundCommunicationEnvelope:
    return OutboundCommunicationEnvelope(
        source_delivery_id=uuid4(),
        location=ConversationLocation(id="C123", type="CHANNEL"),
        text="needs approval",
        **overrides,
    )


def test_an_envelope_stored_before_this_release_still_validates() -> None:
    stored = _envelope().model_dump(mode="json")
    stored.pop("approval", None)

    assert OutboundCommunicationEnvelope.model_validate(stored).approval is None


def test_the_approval_field_survives_the_jsonb_round_trip() -> None:
    stored = _envelope(approval=ApprovalRequest(**_APPROVAL)).model_dump(mode="json")

    restored = OutboundCommunicationEnvelope.model_validate(stored)

    assert restored.approval is not None
    assert restored.approval.run_id == "run-1"
    assert restored.approval.choices == ["once", "deny"]


def test_a_runtime_reply_without_an_approval_is_unchanged() -> None:
    reply = RuntimeReplyCreate(idempotency_key="delivery-1", text="plain reply")

    assert reply.approval is None


def test_choices_are_carried_verbatim_rather_than_assumed() -> None:
    """Hermes narrows the offered set: a smart-denied command gets once/deny only,
    and a non-permanent one gets once/session/deny. Rendering a fixed four would
    offer an option the runtime will reject."""
    narrowed = ApprovalRequest(run_id="run-1", command="x", choices=["once", "deny"])

    assert narrowed.choices == ["once", "deny"]

    with pytest.raises(ValidationError):
        ApprovalRequest(run_id="run-1", command="x", choices=[])


def test_interactive_components_is_a_declared_capability() -> None:
    assert PlatformCapability.INTERACTIVE_COMPONENTS.value == "interactive_components"


def test_a_replica_without_this_release_cannot_read_an_approval_envelope() -> None:
    """Why the write must wait for a separate release. This reconstructs the
    pre-release model to show the failure is a hard ValidationError, not a
    tolerated unknown key -- in production that becomes five failed retries and a
    dead-lettered row that blocks every later reply on the same conversation.
    """
    previous_release = type(
        "PreviousOutboundEnvelope",
        (OutboundCommunicationEnvelope,),
        {
            "__annotations__": {},
            "model_config": ConfigDict(extra="forbid"),
        },
    )
    del previous_release.model_fields["approval"]
    previous_release.model_rebuild(force=True)

    written_by_a_newer_replica = _envelope(approval=ApprovalRequest(**_APPROVAL)).model_dump(mode="json")

    with pytest.raises(ValidationError):
        previous_release.model_validate(written_by_a_newer_replica)
