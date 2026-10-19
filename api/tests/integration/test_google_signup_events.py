"""A Google self-signup records user.signed_up (method google) and organization.created for
its trial Organization, in the transaction that creates them. An invitee enrolled through
Google signs up by invitation. A refused or returning sign-in records no signup."""

import threading
from unittest.mock import patch

from hamcrest import assert_that, equal_to, has_length
from sqlmodel import Session

from api.domains.auth.google_sign_in import GoogleSignInService
from api.domains.events.catalog import ORGANIZATION_CREATED, PRODUCT_ANALYTICS_HANDLER, USER_SIGNED_UP
from api.domains.events.dispatch import EventDeliveryDispatcher
from api.domains.events.models import EventScope, OutboxMessage
from api.domains.events.repository import OutboxMessageRepository
from api.domains.onboarding.repository import TrialSettingsRepository
from api.domains.onboarding.settings_service import TrialSettingsService
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.repository import UserRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.google_sign_in import (
    GOOGLE_EMAIL,
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


def _setup(*steps, signup: bool = True):
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
        trial_settings_are_configured(enabled=signup),
        *steps,
    ]


def _events(context, event_name: str) -> list[OutboxMessage]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [message for message in messages if message.event_name == event_name]


def _handlers(context, event: OutboxMessage) -> list[str]:
    deliveries = context.injector.get(OutboxMessageRepository).list_deliveries_for_event(event.event_id)
    return [delivery.handler_name for delivery in deliveries]


def test_a_google_signup_records_the_signup_and_its_trial_organization():
    with given(_setup()) as context:
        finish_google_sign_in(context)

        user = context.injector.get(UserRepository).get_by_email(GOOGLE_EMAIL)
        organization_id = context.injector.get(OrganizationLookupService).first_created_by(user.id)
        (signed_up,) = _events(context, USER_SIGNED_UP)
        (created,) = _events(context, ORGANIZATION_CREATED)
        user_actor = {"type": "USER", "id": str(user.id), "organization_id": None}
        assert_that(
            (signed_up.event_scope, signed_up.organization_id, signed_up.actor, signed_up.payload),
            equal_to((EventScope.PLATFORM, None, user_actor, {"user_id": str(user.id), "method": "google"})),
        )
        assert_that(
            (created.event_scope, created.organization_id, created.actor, created.payload),
            equal_to(
                (
                    EventScope.ORGANIZATION,
                    organization_id,
                    user_actor,
                    {"organization_id": str(organization_id), "created_by_user_id": str(user.id)},
                )
            ),
        )
        assert_that(
            (_handlers(context, signed_up), _handlers(context, created)),
            equal_to(([PRODUCT_ANALYTICS_HANDLER], [PRODUCT_ANALYTICS_HANDLER])),
        )


def test_the_signup_deliveries_are_enqueued():
    with given(_setup()) as context:
        with patch.object(EventDeliveryDispatcher, "enqueue_immediate") as enqueue:
            finish_google_sign_in(context)

        enqueued = [delivery_id for call in enqueue.call_args_list for delivery_id in call.args[0]]
        expected = [
            delivery_id
            for event in (*_events(context, USER_SIGNED_UP), *_events(context, ORGANIZATION_CREATED))
            for delivery_id in (
                delivery.id
                for delivery in context.injector.get(OutboxMessageRepository).list_deliveries_for_event(event.event_id)
            )
        ]
        assert_that(sorted(enqueued), equal_to(sorted(expected)))
        assert_that(expected, has_length(2))


def test_a_closed_signup_records_nothing():
    with given(_setup(signup=False)) as context:
        response = finish_google_sign_in(context)

        assert_that(redirect_target(response)[1], equal_to({"error": "signup_closed"}))
        assert_that((_events(context, USER_SIGNED_UP), _events(context, ORGANIZATION_CREATED)), equal_to(([], [])))


def test_an_address_that_had_a_trial_records_nothing():
    with given(_setup()) as context:
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            context.injector.get(TrialSettingsService).record_trial(GOOGLE_EMAIL, session)
            session.commit()

        response = finish_google_sign_in(context)

        assert_that(redirect_target(response)[1], equal_to({"error": "trial_used"}))
        assert_that((_events(context, USER_SIGNED_UP), _events(context, ORGANIZATION_CREATED)), equal_to(([], [])))


def test_full_trials_record_nothing():
    with given(_setup(there_is_a_user(email="trial-cap-admin@example.com", is_platform_admin=True))) as context:
        context.injector.get(TrialSettingsRepository).set_settings(
            {"max_active_trials": 1}, context.user.id, "Platform Admin"
        )
        context.injector.get(OrganizationRepository).save(
            Organization(name="Someone's trial", allowed_models=["*"], is_trial=True)
        )

        response = finish_google_sign_in(context)

        assert_that(redirect_target(response)[1], equal_to({"error": "trials_full"}))
        assert_that((_events(context, USER_SIGNED_UP), _events(context, ORGANIZATION_CREATED)), equal_to(([], [])))


def test_an_invitee_enrolled_through_google_signs_up_by_invitation():
    with given(
        _setup(
            there_is_an_organization(name="Acme"), there_is_a_user(role=OrganizationRole.MEMBER, email_verified=False)
        )
    ) as context:
        google_returns(google_identity(email=context.user.email))(context)

        finish_google_sign_in(context)

        (signed_up,) = _events(context, USER_SIGNED_UP)
        assert_that(signed_up.payload, equal_to({"user_id": str(context.user.id), "method": "invite"}))
        assert_that(_events(context, ORGANIZATION_CREATED), equal_to([]))


def test_a_returning_google_user_records_no_second_signup():
    with given(_setup()) as context:
        finish_google_sign_in(context)

        finish_google_sign_in(context)

        assert_that(
            (len(_events(context, USER_SIGNED_UP)), len(_events(context, ORGANIZATION_CREATED))), equal_to((1, 1))
        )


def test_simultaneous_first_sign_ins_record_one_signup():
    with given(_setup()) as context:
        service = context.injector.get(GoogleSignInService)
        barrier = threading.Barrier(2)

        def sign_in() -> None:
            barrier.wait()
            service._sign_in(google_identity())

        threads = [threading.Thread(target=sign_in) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert_that(
            (len(_events(context, USER_SIGNED_UP)), len(_events(context, ORGANIZATION_CREATED))), equal_to((1, 1))
        )
