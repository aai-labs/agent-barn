"""Trial settings (AF-368): Platform Administrators set the credit a new trial
Organization starts with, and every change is audited."""

from uuid import uuid7

import pytest
from hamcrest import assert_that, equal_to, has_entries, has_length, none, not_none
from sqlmodel import Session, select

from api.domains.events.catalog import PLATFORM_TRIAL_SETTINGS_CHANGED
from api.domains.events.models import OutboxMessage
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.events import event_delivery_tables_are_clean
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

BASE = "/api/v1/platform/settings/trial"


def _setup(*steps):
    return [
        set_env_variable({"TRIAL_DEFAULT_CREDIT_USD": "10"}),
        prepare_injector(),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        event_delivery_tables_are_clean(),
        *steps,
    ]


def a_platform_admin():
    def step(context):
        user_id = uuid7()
        there_is_a_user(id=user_id, email=f"platform-{user_id}@example.com", is_platform_admin=True)(context)
        there_is_an_access_token_for_user(user_id)(context)

    return step


def auth(context):
    return {"Authorization": f"Bearer {context.access_token}"}


def _trial_setting_events(context) -> list[OutboxMessage]:
    delegate = context.injector.get(PostgresRepositoryDelegate)
    with Session(delegate.engine) as session:
        return list(
            session.exec(select(OutboxMessage).where(OutboxMessage.event_name == PLATFORM_TRIAL_SETTINGS_CHANGED))
        )


def test_the_deployment_default_applies_until_an_administrator_sets_one():
    with given(_setup(a_platform_admin())) as context:
        with when("a Platform Administrator reads the trial settings"):
            response = context.client.get(BASE, headers=auth(context))

        with then("the deployment default is shown, never saved"):
            assert_that(response.status_code, equal_to(200))
            assert_that(response.json(), has_entries(credit_usd=10.0, agent_limit=1, updated_at=none()))


def test_a_platform_administrator_sets_the_trial_credit():
    with given(_setup(a_platform_admin())) as context:
        with when("they set the credit"):
            saved = context.client.put(BASE, headers=auth(context), json={"credit_usd": 25})

        with then("it is stored and read back"):
            assert_that(saved.status_code, equal_to(200), saved.text)
            assert_that(saved.json(), has_entries(credit_usd=25.0, updated_at=not_none()))
            read = context.client.get(BASE, headers=auth(context))
            assert_that(read.json(), has_entries(credit_usd=25.0))

        with then("the change is audited with its before and after values"):
            events = _trial_setting_events(context)
            assert_that(events, has_length(1))
            assert_that(events[0].payload, has_entries(previous=10.0, current=25.0))


def test_saving_the_same_credit_again_records_nothing_new():
    with given(_setup(a_platform_admin())) as context:
        context.client.put(BASE, headers=auth(context), json={"credit_usd": 25})

        with when("the same credit is saved again"):
            response = context.client.put(BASE, headers=auth(context), json={"credit_usd": 25})

        with then("no second change is audited"):
            assert_that(response.status_code, equal_to(200))
            assert_that(_trial_setting_events(context), has_length(1))


def test_a_platform_administrator_sets_the_trial_agent_limit():
    with given(_setup(a_platform_admin())) as context:
        context.client.put(BASE, headers=auth(context), json={"credit_usd": 25})

        with when("they change only the agent limit"):
            saved = context.client.put(BASE, headers=auth(context), json={"agent_limit": 3})

        with then("it is stored, and the credit is left as it was"):
            assert_that(saved.status_code, equal_to(200), saved.text)
            assert_that(saved.json(), has_entries(credit_usd=25.0, agent_limit=3))

        with then("each change is audited on its own"):
            events = _trial_setting_events(context)
            assert_that(events, has_length(2))
            assert_that(events[1].payload, has_entries(setting="agent_limit", previous=1.0, current=3.0))


@pytest.mark.parametrize("limit", [0, 51, 1.5])
def test_an_invalid_agent_limit_is_refused(limit):
    with given(_setup(a_platform_admin())) as context:
        response = context.client.put(BASE, headers=auth(context), json={"agent_limit": limit})

        assert_that(response.status_code, equal_to(422))


@pytest.mark.parametrize("credit", [-1, 10_001, "lots"])
def test_an_invalid_credit_is_refused(credit):
    with given(_setup(a_platform_admin())) as context:
        with when("an out-of-range or non-numeric credit is saved"):
            response = context.client.put(BASE, headers=auth(context), json={"credit_usd": credit})

        with then("it is refused"):
            assert_that(response.status_code, equal_to(422))


@pytest.mark.parametrize("method,payload", [("GET", None), ("PUT", {"credit_usd": 5})])
def test_an_organization_owner_cannot_manage_trial_settings(method, payload):
    with given(_setup(there_is_an_organization_with_user_and_access_token())) as context:
        with when("an Organization Owner without Platform Privilege tries"):
            response = context.client.request(method, BASE, headers=auth(context), json=payload)

        with then("they are refused"):
            assert_that(response.status_code, equal_to(403))


def test_an_unauthenticated_caller_cannot_read_trial_settings():
    with given(_setup()) as context:
        response = context.client.get(BASE)
        assert_that(response.status_code, equal_to(401))
