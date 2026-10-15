"""Finishing onboarding records user.onboarding.completed once per user: scoped to the
trial Organization the user created, or to the platform when they created none."""

import threading

from hamcrest import assert_that, equal_to, has_length

from api.domains.events.catalog import PRODUCT_ANALYTICS_HANDLER, USER_ONBOARDING_COMPLETED
from api.domains.events.models import EventScope, OutboxMessage
from api.domains.events.repository import OutboxMessageRepository
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.users.repository import UserRepository
from api.domains.users.service import UserService
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.google_sign_in import GOOGLE_EMAIL, WEB_APP_URL, FakeGoogleIdentityModule, finish_google_sign_in
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

COMPLETE = "/api/v1/onboarding/complete"


def _setup(*steps):
    return [
        set_env_variable(
            {
                "WEB_APP_URL": WEB_APP_URL,
                "SELF_SIGNUP_ENABLED": "true",
                "AGENTBARN_TELEGRAM_BOT_TOKEN": "424242:the-shared-bot-token",
                "AGENTBARN_TELEGRAM_BOT_USERNAME": "AgentBarnTestBot",
            }
        ),
        prepare_injector(modules=[FakeGoogleIdentityModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        *steps,
    ]


def someone_signed_up_with_google():
    def step(context):
        finish_google_sign_in(context)
        context.access_token = context.client.post("/api/v1/auth/refresh").json()["access_token"]
        context.user = context.injector.get(UserRepository).get_by_email(GOOGLE_EMAIL)

    return step


def _complete(context):
    return context.client.post(COMPLETE, headers={"Authorization": f"Bearer {context.access_token}"})


def _completed_events(context) -> list[OutboxMessage]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [message for message in messages if message.event_name == USER_ONBOARDING_COMPLETED]


def test_finishing_onboarding_records_one_event_in_the_trial_organization():
    with given(_setup(someone_signed_up_with_google())) as context:
        response = _complete(context)

        assert_that(response.status_code, equal_to(204))
        trial_id = context.injector.get(OrganizationLookupService).first_created_by(context.user.id)
        events = _completed_events(context)
        assert_that(events, has_length(1))
        assert_that(
            (events[0].event_scope, events[0].organization_id, events[0].actor, events[0].payload),
            equal_to(
                (
                    EventScope.ORGANIZATION,
                    trial_id,
                    {"type": "USER", "id": str(context.user.id), "organization_id": None},
                    {"user_id": str(context.user.id)},
                )
            ),
        )
        deliveries = context.injector.get(OutboxMessageRepository).list_deliveries_for_event(events[0].event_id)
        assert_that([delivery.handler_name for delivery in deliveries], equal_to([PRODUCT_ANALYTICS_HANDLER]))


def test_finishing_again_records_nothing_more():
    with given(_setup(someone_signed_up_with_google())) as context:
        _complete(context)

        second = _complete(context)

        assert_that(second.status_code, equal_to(204))
        assert_that(_completed_events(context), has_length(1))


def test_a_user_who_created_no_organization_records_a_platform_event():
    with given(_setup(there_is_an_organization_with_user_and_access_token())) as context:
        _complete(context)

        events = _completed_events(context)
        assert_that(events, has_length(1))
        assert_that((events[0].event_scope, events[0].organization_id), equal_to((EventScope.PLATFORM, None)))


def test_simultaneous_completions_record_one_event():
    with given(_setup(someone_signed_up_with_google())) as context:
        service = context.injector.get(UserService)
        barrier = threading.Barrier(2)

        def complete() -> None:
            barrier.wait()
            service.complete_onboarding(context.user.id, None)

        threads = [threading.Thread(target=complete) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert_that(_completed_events(context), has_length(1))
        assert_that(
            context.injector.get(UserRepository).get(context.user.id).onboarding_completed_at is not None,
            equal_to(True),
        )
