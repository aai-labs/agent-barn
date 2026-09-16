from hamcrest import assert_that, equal_to

from api.domains.communications.models import ApprovalRequest
from api.domains.communications.plugins.approvals import (
    APPROVAL_CHOICE_CODES,
    SYNTHESIZED_MESSAGE_PREFIX,
    decode_approval_component,
    decode_approval_value,
    encode_approval_component,
    encode_approval_value,
    is_approval_component,
    is_synthesized_message_id,
)


def test_an_approval_value_round_trips_through_an_id_that_contains_colons() -> None:
    value = encode_approval_value("run_abc:1726051234.5", "session")

    assert_that(value, equal_to("run_abc:1726051234.5:session"))
    assert_that(decode_approval_value(value), equal_to(("run_abc:1726051234.5", "session")))


def test_a_synthesized_message_id_is_recognised() -> None:
    assert_that(is_synthesized_message_id(f"{SYNTHESIZED_MESSAGE_PREFIX}1724320900.000200"), equal_to(True))
    assert_that(is_synthesized_message_id("1724320800.000100"), equal_to(False))
    assert_that(is_synthesized_message_id(""), equal_to(False))
    assert_that(is_synthesized_message_id(None), equal_to(False))


def test_every_runtime_choice_has_a_label() -> None:
    approval = ApprovalRequest(
        approval_id="run_abc:1.0", command="echo hello", choices=["once", "session", "always", "deny"]
    )

    assert_that(set(approval.choice_labels), equal_to({"once", "session", "always", "deny"}))


def test_every_runtime_choice_round_trips_through_its_compact_code() -> None:
    approval = ApprovalRequest(
        approval_id="run_abc:1.0", command="echo hello", choices=["once", "session", "always", "deny"]
    )
    for choice in approval.choice_labels:
        value = encode_approval_component("thread-1", "run_abc:1726051234.5", choice)

        assert_that(decode_approval_component(value), equal_to(("thread-1", "run_abc:1726051234.5", choice)))


def test_a_choice_the_runtime_invents_is_carried_whole() -> None:
    value = encode_approval_component("thread-1", "run_abc:1.0", "escalate")

    assert_that(decode_approval_component(value), equal_to(("thread-1", "run_abc:1.0", "escalate")))


def test_a_component_value_from_another_app_is_not_ours() -> None:
    assert_that(is_approval_component("some_other_app:button"), equal_to(False))
    assert_that(decode_approval_component("some_other_app:button"), equal_to(("", "", "")))


def test_each_compact_code_is_distinct() -> None:
    approval = ApprovalRequest(
        approval_id="run_abc:1.0", command="echo hello", choices=["once", "session", "always", "deny"]
    )

    assert_that(len(set(APPROVAL_CHOICE_CODES.values())), equal_to(len(APPROVAL_CHOICE_CODES)))
    assert_that(set(APPROVAL_CHOICE_CODES), equal_to(set(approval.choice_labels)))
