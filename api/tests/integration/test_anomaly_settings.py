"""Turning anomaly detection on for an Organization, and adjusting an Agent's normal (AF-453).

The contract under test:

- detection is off until an Owner or Admin turns it on; Members cannot see or change it;
- an Owner or Admin may set an Agent's sensitivity and hard caps; nobody else may,
  including a Member who owns the Agent;
- every change leaves an audit Event behind, and an unchanged value leaves none.
"""

from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, empty, equal_to, has_entries

from api.domains.events.models import OutboxMessage
from api.domains.rbac.catalog import AGENT_OWNER_ROLE_ID, OrganizationRole
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_agent_access,
    there_is_an_agent,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_BASE = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
]

DETECTION = "/api/v1/organizations/{organization_id}/anomaly-detection"
OVERRIDE = "/api/v1/organizations/{organization_id}/agents/{agent_id}/anomaly-override"
SETTINGS_CHANGED = "organization.anomaly_detection.changed"
OVERRIDE_CHANGED = "agent.anomaly_override.changed"


def signed_in(role: OrganizationRole = OrganizationRole.OWNER) -> list:
    """An Organization has exactly one Owner, so the Owner founds it; anyone else joins."""
    email = f"{role.value.lower()}@example.com"
    if role is OrganizationRole.OWNER:
        people = [there_is_a_user(email=email), there_is_an_organization()]
    else:
        people = [there_is_an_organization(), there_is_a_user(email=email, role=role)]
    return [*_BASE, *people, there_is_an_access_token_for_user()]


def auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def events_named(context, name: str) -> list[OutboxMessage]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [message for message in messages if message.event_name == name]


def get_detection(context, organization_id=None):
    return context.client.get(
        DETECTION.format(organization_id=organization_id or context.organization.id), headers=auth(context)
    )


def put_detection(context, enabled: bool):
    return context.client.put(
        DETECTION.format(organization_id=context.organization.id), json={"enabled": enabled}, headers=auth(context)
    )


def put_override(context, body: dict):
    return context.client.put(
        OVERRIDE.format(organization_id=context.organization.id, agent_id=context.agent.id),
        json=body,
        headers=auth(context),
    )


def test_detection_is_off_until_turned_on():
    with given(signed_in()) as context:
        response = get_detection(context)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json(), has_entries(enabled=False, can_manage=True))


def test_an_owner_turns_detection_on():
    with given(signed_in()) as context:
        with when("the Owner turns detection on"):
            response = put_detection(context, True)

        with then("it is on, now and on the next read"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(get_detection(context).json(), has_entries(enabled=True))


def test_an_admin_turns_detection_on():
    with given(signed_in(OrganizationRole.ADMIN)) as context:
        response = put_detection(context, True)

        assert_that(response.json(), has_entries(enabled=True))


def test_a_member_cannot_see_whether_detection_is_on():
    with given(signed_in(OrganizationRole.MEMBER)) as context:
        assert_that(get_detection(context).status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_member_cannot_turn_detection_on():
    with given(signed_in(OrganizationRole.MEMBER)) as context:
        assert_that(put_detection(context, True).status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_an_organization_the_caller_does_not_belong_to_is_out_of_reach():
    with given(signed_in()) as context:
        response = get_detection(context, organization_id=uuid7())

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_turning_detection_on_is_audited():
    with given(signed_in()) as context:
        put_detection(context, True)

        (event,) = events_named(context, SETTINGS_CHANGED)
        assert_that(event.payload, has_entries(enabled=True, previous_enabled=False))


def test_saving_the_same_value_leaves_no_audit_event():
    with given(signed_in()) as context:
        put_detection(context, False)

        assert_that(events_named(context, SETTINGS_CHANGED), empty())


def test_an_owner_sets_an_agents_sensitivity_and_caps():
    with given([*signed_in(), there_is_an_agent()]) as context:
        response = put_override(
            context, {"sensitivity": "HIGH", "max_llm_tokens_per_hour": 200_000, "max_llm_calls_per_hour": 120}
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            response.json(),
            equal_to({"sensitivity": "HIGH", "max_llm_tokens_per_hour": 200_000, "max_llm_calls_per_hour": 120}),
        )


def test_omitted_caps_are_cleared():
    with given([*signed_in(), there_is_an_agent()]) as context:
        put_override(context, {"sensitivity": "LOW", "max_llm_calls_per_hour": 120})

        response = put_override(context, {"sensitivity": "LOW"})

        assert_that(response.json(), has_entries(max_llm_calls_per_hour=None))


def test_a_cap_must_be_positive():
    with given([*signed_in(), there_is_an_agent()]) as context:
        response = put_override(context, {"sensitivity": "NORMAL", "max_llm_calls_per_hour": 0})

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))


def test_changing_an_override_is_audited():
    with given([*signed_in(), there_is_an_agent()]) as context:
        put_override(context, {"sensitivity": "HIGH", "max_llm_calls_per_hour": 120})

        (event,) = events_named(context, OVERRIDE_CHANGED)
        assert_that(
            event.payload,
            has_entries(
                agent_id=str(context.agent.id),
                sensitivity="HIGH",
                previous_sensitivity="NORMAL",
                max_llm_calls_per_hour=120,
                previous_max_llm_calls_per_hour=None,
            ),
        )


def test_saving_an_unchanged_override_leaves_no_audit_event():
    with given([*signed_in(), there_is_an_agent()]) as context:
        put_override(context, {"sensitivity": "NORMAL"})

        assert_that(events_named(context, OVERRIDE_CHANGED), empty())


def test_a_member_who_owns_the_agent_cannot_change_its_normal():
    with given(
        [
            *signed_in(OrganizationRole.MEMBER),
            there_is_an_agent(),
            there_is_agent_access(access_role_id=AGENT_OWNER_ROLE_ID),
        ]
    ) as context:
        response = put_override(context, {"sensitivity": "LOW"})

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_member_without_access_cannot_even_see_the_agent():
    with given([*signed_in(OrganizationRole.MEMBER), there_is_an_agent()]) as context:
        response = put_override(context, {"sensitivity": "LOW"})

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
