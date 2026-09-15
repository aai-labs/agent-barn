from api.domains.communications.plugins.approvals import (
    APPROVAL_CHOICE_LABELS,
    SYNTHESIZED_MESSAGE_PREFIX,
    decode_approval_value,
    encode_approval_value,
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
