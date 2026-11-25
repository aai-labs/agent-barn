from uuid import uuid7

import pytest
from hamcrest import assert_that, equal_to

from api.domains.llm_providers.access import can_use
from api.domains.llm_providers.models import OrganizationAccess

LISTED = uuid7()
UNLISTED = uuid7()


@pytest.mark.parametrize(
    ("mode", "listed", "unlisted", "new"),
    [
        (OrganizationAccess.ALL, True, True, True),
        (OrganizationAccess.NONE, False, False, False),
        (OrganizationAccess.ALL_EXCEPT, False, True, True),
        (OrganizationAccess.ONLY, True, False, False),
    ],
)
def test_an_organization_can_use_a_connection_as_its_mode_and_list_say(mode, listed, unlisted, new):
    answers = (can_use(mode, {LISTED}, LISTED), can_use(mode, {LISTED}, UNLISTED), can_use(mode, {LISTED}, None))

    assert_that(answers, equal_to((listed, unlisted, new)))
