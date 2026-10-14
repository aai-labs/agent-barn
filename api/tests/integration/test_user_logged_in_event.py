from unittest.mock import patch

from fastapi import status
from hamcrest import assert_that, equal_to

from api.domains.events.catalog import PRODUCT_ANALYTICS_HANDLER, USER_LOGGED_IN
from api.domains.events.models import EventScope, OutboxMessage
from api.domains.events.repository import OutboxMessageRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user

EMAIL = "login-event@example.com"
PASSWORD = "StrongPass123"

_GIVEN = [
    prepare_injector(),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_a_user(email=EMAIL, password=PASSWORD),
]


def _login(context, password: str = PASSWORD, email: str = EMAIL):
    return context.client.post("/api/v1/auth/login", data={"username": email, "password": password})


def _login_events(context) -> list[OutboxMessage]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [message for message in messages if message.event_name == USER_LOGGED_IN]


def test_a_successful_login_records_one_platform_scoped_user_logged_in():
    with given(_GIVEN) as context:
        response = _login(context)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        events = _login_events(context)
        assert_that(len(events), equal_to(1))
        assert_that(
            (events[0].event_scope, events[0].organization_id, events[0].actor, events[0].payload),
            equal_to(
                (
                    EventScope.PLATFORM,
                    None,
                    {"type": "USER", "id": str(context.user.id), "organization_id": None},
                    {"user_id": str(context.user.id), "method": "password"},
                )
            ),
        )
        deliveries = context.injector.get(OutboxMessageRepository).list_deliveries_for_event(events[0].event_id)
        assert_that([delivery.handler_name for delivery in deliveries], equal_to([PRODUCT_ANALYTICS_HANDLER]))


def test_a_failed_login_records_nothing():
    with given(_GIVEN) as context:
        wrong_password = _login(context, password="WrongPass123")
        unknown_email = _login(context, email="nobody@example.com")

        assert_that((wrong_password.status_code, unknown_email.status_code), equal_to((401, 401)))
        assert_that(_login_events(context), equal_to([]))


def test_refreshing_a_token_records_no_login():
    with given(_GIVEN) as context:
        tokens = _login(context).json()

        refreshed = context.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

        assert_that(refreshed.status_code, equal_to(status.HTTP_200_OK))
        assert_that(len(_login_events(context)), equal_to(1))


def test_using_an_api_key_records_no_login():
    with given(_GIVEN) as context:
        access = _login(context).json()["access_token"]
        created = context.client.post(
            "/api/v1/auth/me/api-keys",
            json={"name": "Automation", "access_mode": "READ_ONLY"},
            headers={"Authorization": f"Bearer {access}"},
        ).json()

        me = context.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {created['token']}"})

        assert_that(me.status_code, equal_to(status.HTTP_200_OK))
        assert_that(len(_login_events(context)), equal_to(1))


def test_a_failure_to_record_the_login_never_fails_the_login():
    with given(_GIVEN) as context:
        with patch.object(OutboxMessageRepository, "create", side_effect=RuntimeError("outbox down")):
            response = _login(context)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(_login_events(context), equal_to([]))
