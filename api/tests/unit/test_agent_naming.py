import string

import pytest
from hamcrest import assert_that, equal_to, is_in

from api.domains.agents.naming import NAMES_BY_INITIAL, choose_first_name


@pytest.mark.parametrize("count", range(53))
def test_suggestion_uses_alphabetical_initial_and_wraps(count):
    name = choose_first_name(count)
    assert_that(name[0], equal_to(string.ascii_uppercase[count % 26]))
    assert_that(name, is_in(NAMES_BY_INITIAL[count % 26]))


def test_name_groups_have_distinct_spellings_and_correct_initials():
    assert_that(len(NAMES_BY_INITIAL), equal_to(26))
    for initial, names in zip(string.ascii_uppercase, NAMES_BY_INITIAL, strict=True):
        assert_that(len(names), equal_to(len(set(names))))
        assert_that({name[0] for name in names}, equal_to({initial}))
