from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid7

import pytest
from fastapi import status
from hamcrest import assert_that, equal_to

from api.domains.auth.models import PasswordResetToken
from api.domains.auth.service import AuthService
from api.domains.events.catalog import PRODUCT_ANALYTICS_HANDLER, USER_SIGNED_UP
from api.domains.events.models import EventScope, OutboxMessage
from api.domains.events.repository import OutboxMessageRepository
from api.domains.users.models import User
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

NEW_PASSWORD = "InviteePass123!"


def _given():
    admin_id = uuid7()
    return [
        prepare_injector(),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_a_user(id=admin_id, email="signup-admin@example.com", is_platform_admin=True),
        there_is_an_access_token_for_user(user_id=admin_id),
    ]


def _invite(context) -> tuple[UUID, str]:
    created = context.client.post(
        "/api/v1/platform/users",
        json={"email": f"invitee-{uuid7()}@example.com", "organization_name": "Invitee Org"},
        headers={"Authorization": f"Bearer {context.access_token}"},
    ).json()
    link = created["invite_link"]
    token = parse_qs(urlparse(link).query).get("token", [None])[0] or link.rstrip("/").split("/")[-1]
    return UUID(created["user"]["id"]), token


def _accept(context, token: str):
    return context.client.post(
        "/api/v1/auth/set-password",
        json={"token": token, "new_password": NEW_PASSWORD, "full_name": "New Member"},
    )


def _signup_events(context) -> list[OutboxMessage]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [message for message in messages if message.event_name == USER_SIGNED_UP]


def test_accepting_an_invite_records_one_platform_scoped_user_signed_up():
    with given(_given()) as context:
        user_id, token = _invite(context)

        response = _accept(context, token)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        events = _signup_events(context)
        assert_that(len(events), equal_to(1))
        assert_that(
            (events[0].event_scope, events[0].organization_id, events[0].actor, events[0].payload),
            equal_to(
                (
                    EventScope.PLATFORM,
                    None,
                    {"type": "USER", "id": str(user_id), "organization_id": None},
                    {"user_id": str(user_id)},
                )
            ),
        )
        deliveries = context.injector.get(OutboxMessageRepository).list_deliveries_for_event(events[0].event_id)
        assert_that([delivery.handler_name for delivery in deliveries], equal_to([PRODUCT_ANALYTICS_HANDLER]))


def test_reusing_the_invite_token_records_nothing_more():
    with given(_given()) as context:
        _, token = _invite(context)
        _accept(context, token)

        again = _accept(context, token)

        assert_that(again.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(len(_signup_events(context)), equal_to(1))


def test_a_password_reset_is_not_a_signup():
    with given(_given()) as context:
        user_id, _ = _invite(context)
        reset_token = context.injector.get(AuthService).generate_password_reset_token(user_id)

        response = context.client.post(
            "/api/v1/auth/reset-password", json={"token": reset_token, "new_password": NEW_PASSWORD}
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(_signup_events(context), equal_to([]))


def test_a_failed_event_write_leaves_the_password_and_token_unchanged():
    with given(_given()) as context:
        user_id, token = _invite(context)
        delegate = context.injector.get(PostgresRepositoryDelegate)
        password_before = delegate.find_by_id(User, user_id).hashed_password

        with (
            patch.object(OutboxMessageRepository, "stage", side_effect=RuntimeError("outbox down")),
            pytest.raises(RuntimeError),
        ):
            _accept(context, token)

        user = delegate.find_by_id(User, user_id)
        assert_that((user.hashed_password, user.email_verified_at), equal_to((password_before, None)))
        unused = delegate.find_all(PasswordResetToken, user_id=user_id, is_used=False)
        assert_that(len(unused), equal_to(1))
        assert_that(_signup_events(context), equal_to([]))
