from hamcrest import assert_that, equal_to

from api.domains.communications.plugins.approvals import (
    SYNTHESIZED_MESSAGE_PREFIX,
    decode_approval_value,
    encode_approval_value,
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
