from api.domains.communications.plugins.approvals import (
    APPROVAL_CHOICE_CODES,
    APPROVAL_CHOICE_LABELS,
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

    assert value == "run_abc:1726051234.5:session"
    assert decode_approval_value(value) == ("run_abc:1726051234.5", "session")


def test_a_synthesized_message_id_is_recognised() -> None:
    assert is_synthesized_message_id(f"{SYNTHESIZED_MESSAGE_PREFIX}1724320900.000200") is True
    assert is_synthesized_message_id("1724320800.000100") is False
    assert is_synthesized_message_id("") is False
    assert is_synthesized_message_id(None) is False


def test_every_runtime_choice_has_a_label() -> None:
    assert set(APPROVAL_CHOICE_LABELS) == {"once", "session", "always", "deny"}


def test_every_runtime_choice_round_trips_through_its_compact_code() -> None:
    for choice in APPROVAL_CHOICE_LABELS:
        value = encode_approval_component("thread-1", "run_abc:1726051234.5", choice)

        assert decode_approval_component(value) == ("thread-1", "run_abc:1726051234.5", choice)


def test_a_choice_the_runtime_invents_is_carried_whole() -> None:
    value = encode_approval_component("thread-1", "run_abc:1.0", "escalate")

    assert decode_approval_component(value) == ("thread-1", "run_abc:1.0", "escalate")


def test_a_component_value_from_another_app_is_not_ours() -> None:
    assert is_approval_component("some_other_app:button") is False
    assert decode_approval_component("some_other_app:button") == ("", "", "")


def test_each_compact_code_is_distinct() -> None:
    assert len(set(APPROVAL_CHOICE_CODES.values())) == len(APPROVAL_CHOICE_CODES)
    assert set(APPROVAL_CHOICE_CODES) == set(APPROVAL_CHOICE_LABELS)
