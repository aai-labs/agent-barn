"""An Organization's Owners and Admins turn unusual activity emails on or off (AF-464).

The contract under test:

- alerts are on unless turned off, so turning detection on is enough to hear about
  what it flags;
- Owners and Admins may turn them off and on again, Members may not, and turning them
  off leaves detection as it was;
- every change leaves an audit Event behind, and an unchanged value leaves none.
"""

from fastapi import status
from hamcrest import assert_that, empty, equal_to, has_entries

from api.domains.rbac.catalog import OrganizationRole
from api.tests.core.givenpy import given, then, when
from api.tests.integration.test_anomaly_settings import (
    DETECTION,
    SETTINGS_CHANGED,
    auth,
    events_named,
    get_detection,
    put_detection,
    signed_in,
)

ALERTS_CHANGED = "organization.anomaly_alerts.changed"


def put_alerts(context, alerts_enabled: bool):
    return context.client.put(
        DETECTION.format(organization_id=context.organization.id),
        json={"alerts_enabled": alerts_enabled},
        headers=auth(context),
    )


def test_alerts_are_on_unless_turned_off():
    with given(signed_in()) as context:
        assert_that(get_detection(context).json(), has_entries(alerts_enabled=True))


def test_an_owner_turns_alerts_off_and_detection_stays_as_it_was():
    with given(signed_in()) as context:
        put_detection(context, True)

        with when("the Owner turns alerts off"):
            response = put_alerts(context, False)

        with then("alerts are off and detection is still on, now and on the next read"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json(), has_entries(enabled=True, alerts_enabled=False))
            assert_that(get_detection(context).json(), has_entries(enabled=True, alerts_enabled=False))


def test_turning_detection_on_or_off_leaves_alerts_as_they_were():
    with given(signed_in()) as context:
        put_alerts(context, False)

        put_detection(context, True)
        response = put_detection(context, False)

        assert_that(response.json(), has_entries(enabled=False, alerts_enabled=False))


def test_an_admin_turns_alerts_off():
    with given(signed_in(OrganizationRole.ADMIN)) as context:
        assert_that(put_alerts(context, False).json(), has_entries(alerts_enabled=False))


def test_a_member_cannot_turn_alerts_off():
    with given(signed_in(OrganizationRole.MEMBER)) as context:
        assert_that(put_alerts(context, False).status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_change_must_say_what_it_changes():
    with given(signed_in()) as context:
        response = context.client.put(
            DETECTION.format(organization_id=context.organization.id), json={}, headers=auth(context)
        )

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))


def test_turning_alerts_off_is_audited_on_its_own():
    with given(signed_in()) as context:
        put_alerts(context, False)

        (event,) = events_named(context, ALERTS_CHANGED)
        assert_that(event.payload, has_entries(alerts_enabled=False, previous_alerts_enabled=True))
        assert_that(events_named(context, SETTINGS_CHANGED), empty())


def test_saving_the_same_alerts_value_leaves_no_audit_event():
    with given(signed_in()) as context:
        put_alerts(context, True)

        assert_that(events_named(context, ALERTS_CHANGED), empty())
