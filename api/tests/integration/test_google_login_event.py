"""A Google sign-in to an existing, verified account records user.logged_in with method
google. Creating an account or enrolling an invitee is a sign-up, not a login."""

import threading
from unittest.mock import patch

from hamcrest import assert_that, equal_to, has_length

from api.domains.auth.google_sign_in import GoogleSignInService
from api.domains.events.catalog import PRODUCT_ANALYTICS_HANDLER, USER_LOGGED_IN
from api.domains.events.models import EventScope, OutboxMessage
from api.domains.events.repository import OutboxMessageRepository
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.google_sign_in import (
    WEB_APP_URL,
    FakeGoogleIdentityModule,
    finish_google_sign_in,
    google_identity,
    google_returns,
    redirect_target,
)
from api.tests.steps.onboarding import trial_settings_are_configured
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.user import there_is_a_user

DASHBOARD = f"{WEB_APP_URL}/dashboard"


def _setup(*steps):
    return [
        set_env_variable(
            {
                "WEB_APP_URL": WEB_APP_URL,
                "AGENTBARN_TELEGRAM_BOT_TOKEN": "424242:the-shared-bot-token",
                "AGENTBARN_TELEGRAM_BOT_USERNAME": "AgentBarnTestBot",
            }
        ),
        prepare_injector(modules=[FakeGoogleIdentityModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        trial_settings_are_configured(),
        *steps,
    ]


def _login_events(context) -> list[OutboxMessage]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [message for message in messages if message.event_name == USER_LOGGED_IN]


def test_a_returning_google_user_records_one_google_login():
    with given(_setup()) as context:
        finish_google_sign_in(context)

        finish_google_sign_in(context)

        events = _login_events(context)
        assert_that(events, has_length(1))
        user_id = str(events[0].payload["user_id"])
        assert_that(
            (events[0].event_scope, events[0].organization_id, events[0].actor, events[0].payload),
            equal_to(
                (
                    EventScope.PLATFORM,
                    None,
                    {"type": "USER", "id": user_id, "organization_id": None},
                    {"user_id": user_id, "method": "google"},
                )
            ),
        )
        deliveries = context.injector.get(OutboxMessageRepository).list_deliveries_for_event(events[0].event_id)
        assert_that([delivery.handler_name for delivery in deliveries], equal_to([PRODUCT_ANALYTICS_HANDLER]))


def test_a_first_google_sign_in_records_no_login():
    with given(_setup()) as context:
        finish_google_sign_in(context)

        assert_that(_login_events(context), equal_to([]))


def test_linking_google_to_an_existing_verified_account_records_a_google_login():
    with given(
        _setup(
            there_is_an_organization(name="Acme"),
            there_is_a_user(email="Jane@Example.com", role=OrganizationRole.MEMBER),
        )
    ) as context:
        response = finish_google_sign_in(context)

        assert_that(redirect_target(response), equal_to((DASHBOARD, {})))
        events = _login_events(context)
        assert_that(events, has_length(1))
        assert_that(events[0].payload, equal_to({"user_id": str(context.user.id), "method": "google"}))


def test_an_invitee_enrolling_through_google_records_no_login():
    with given(
        _setup(
            there_is_an_organization(name="Acme"), there_is_a_user(role=OrganizationRole.MEMBER, email_verified=False)
        )
    ) as context:
        google_returns(google_identity(email=context.user.email))(context)

        finish_google_sign_in(context)

        assert_that(_login_events(context), equal_to([]))


def test_simultaneous_first_sign_ins_are_neither_counted_as_returning():
    with given(_setup()) as context:
        service = context.injector.get(GoogleSignInService)
        barrier = threading.Barrier(2)
        returning = []

        def sign_in() -> None:
            barrier.wait()
            returning.append(service._sign_in(google_identity()).returning)

        threads = [threading.Thread(target=sign_in) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert_that(returning, equal_to([False, False]))


def test_a_failure_to_record_the_login_never_fails_the_google_sign_in():
    with given(_setup()) as context:
        finish_google_sign_in(context)

        with patch.object(OutboxMessageRepository, "create", side_effect=RuntimeError("outbox down")):
            response = finish_google_sign_in(context)

        assert_that(redirect_target(response)[0], equal_to(f"{WEB_APP_URL}/onboarding"))
        assert_that(response.cookies, has_length(1))
        assert_that(_login_events(context), equal_to([]))
