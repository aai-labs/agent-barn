import re
from uuid import uuid7

from fastapi import status
from hamcrest import (
    assert_that,
    contains_string,
    equal_to,
    has_key,
    has_length,
    is_not,
    none,
)
from starlette.testclient import TestClient

from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.mocks.email import MockEmailModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization,
)
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user
from api.domains.users.organization_users.models import OrganizationRole


def _extract_token_from_email(email_html: str) -> str:
    match = re.search(r"token=([^\"&]+)", email_html)
    assert match is not None
    return match.group(1)


def test_refresh_works_with_cookie_and_revokes_previous_token():
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(email="cookie-user@example.com", password="password"),
        ]
    ) as context:
        client: TestClient = context.client

        login_response = client.post(
            "/api/v1/auth/login",
            data={"username": "cookie-user@example.com", "password": "password"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        old_refresh = login_response.json()["refresh_token"]

        with when("I refresh using cookie without request body"):
            refresh_response = client.post("/api/v1/auth/refresh")
            with then("a new token pair is returned"):
                assert_that(refresh_response.status_code, equal_to(status.HTTP_200_OK))
                payload = refresh_response.json()
                assert_that(payload["access_token"], is_not(none()))
                assert_that(payload["refresh_token"], is_not(equal_to(old_refresh)))

        with when("I try to use previous refresh token"):
            stale_response = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
            with then("it is rejected"):
                assert_that(stale_response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_refresh_requires_token():
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.post("/api/v1/auth/refresh")
        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
        assert_that(response.json()["detail"], equal_to("Refresh token is required"))


def test_signup_is_disabled():
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "verify-flow@example.com",
                "password": "StrongPass123",
                "full_name": "Verify Flow",
            },
        )
        assert_that(response.status_code, equal_to(status.HTTP_410_GONE))


def test_signup_org_sees_global_predefined_templates():
    """Signup is disabled at the route, but the service must let a new org see the
    global predefined template catalog (predefined templates are platform/global
    resources, not per-org seeds) if signup is re-enabled."""
    from fastapi import BackgroundTasks

    from api.domains.auth.models import SignupRequest
    from api.domains.auth.service import AuthService
    from api.domains.templates.predefined import PREDEFINED_TEMPLATES
    from api.domains.templates.repository import TemplateRepository
    from api.domains.templates.service import TemplateService
    from api.domains.users.organization_users.repository import (
        OrganizationUserRepository,
    )
    from api.domains.users.repository import UserRepository

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
        ]
    ) as context:
        context.injector.get(TemplateService).seed_predefined_templates()
        context.injector.get(AuthService).signup(
            SignupRequest(
                email="signup-seed@example.com",
                password="StrongPass123",
                full_name="Seed User",
            ),
            BackgroundTasks(),
        )

        user = context.injector.get(UserRepository).get_by_email("signup-seed@example.com")
        assert_that(user, is_not(none()))
        memberships = context.injector.get(OrganizationUserRepository).get_by_user_id(user.id)
        org_id = memberships[0].organization_id

        template_repo = context.injector.get(TemplateRepository)
        visible = template_repo.get_latest_template(org_id, PREDEFINED_TEMPLATES[0].slug)
        assert_that(visible, is_not(none()))
        assert_that(visible.organization_id, none())


def test_me_returns_safe_user_and_organizations():
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                name="Me Contract",
                email="me-contract@example.com",
            ),
            there_is_an_organization(name="Test Organization", owner_id=None),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        client: TestClient = context.client

        me_response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(me_response.status_code, equal_to(status.HTTP_200_OK))
        payload = me_response.json()
        assert_that(payload["email"], equal_to("me-contract@example.com"))
        assert_that(payload, has_key("organization_users"))
        assert_that(payload["organization_users"], has_length(1))
        assert_that(
            payload["organization_users"][0]["organization"]["name"],
            contains_string("Organization"),
        )
        assert_that(payload, is_not(has_key("hashed_password")))
        assert_that(payload, is_not(has_key("security_stamp")))
        assert_that(payload, is_not(has_key("organization_ids")))
        assert_that(payload, is_not(has_key("user_organization_map")))
        assert_that(payload, is_not(has_key("current_user_organization")))


def test_me_works_without_active_organization_header():
    """Bootstrapping account context via /me does not require an active Organization."""
    own_org = uuid7()
    user_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=user_id,
                email="fresh-signup@example.com",
                organization_id=own_org,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=user_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        payload = response.json()
        assert_that(payload["email"], equal_to("fresh-signup@example.com"))
        assert_that(payload["organization_users"], has_length(1))
        assert_that(
            payload["organization_users"][0]["organization_id"],
            equal_to(str(own_org)),
        )


def test_forgot_and_reset_password_flow():
    email_module = MockEmailModule()
    with given(
        [
            prepare_injector(modules=[email_module]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                email="reset-flow@example.com",
                password="OldPassword123",
                email_verified=True,
            ),
        ]
    ) as context:
        client: TestClient = context.client

        forgot_response = client.post("/api/v1/auth/forgot-password", json={"email": "reset-flow@example.com"})
        assert_that(forgot_response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            forgot_response.json()["message"],
            contains_string("Password reset email sent"),
        )
        assert_that(email_module.emails, has_length(1))

        token = _extract_token_from_email(email_module.emails[0].html_part)
        reset_response = client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "NewPassword123"},
        )
        assert_that(reset_response.status_code, equal_to(status.HTTP_200_OK))

        old_login = client.post(
            "/api/v1/auth/login",
            data={"username": "reset-flow@example.com", "password": "OldPassword123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert_that(old_login.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))

        new_login = client.post(
            "/api/v1/auth/login",
            data={"username": "reset-flow@example.com", "password": "NewPassword123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert_that(new_login.status_code, equal_to(status.HTTP_200_OK))


def test_forgot_password_for_unknown_user_is_noop():
    email_module = MockEmailModule()
    with given(
        [
            prepare_injector(modules=[email_module]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.post("/api/v1/auth/forgot-password", json={"email": "missing@example.com"})
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(email_module.emails, has_length(0))


def test_reset_token_is_opaque_not_a_jwt():
    """Reset/invite tokens are opaque random strings, not signed JWTs."""
    email_module = MockEmailModule()
    with given(
        [
            prepare_injector(modules=[email_module]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(email="opaque@example.com", email_verified=True),
        ]
    ) as context:
        client: TestClient = context.client
        client.post("/api/v1/auth/forgot-password", json={"email": "opaque@example.com"})
        token = _extract_token_from_email(email_module.emails[0].html_part)
        # A JWT has exactly two '.' separators; an opaque token has none.
        assert_that(token.count("."), equal_to(0))


def test_new_reset_request_invalidates_previous_token():
    """Requesting a fresh reset link invalidates any earlier, still-unused one."""
    email_module = MockEmailModule()
    with given(
        [
            prepare_injector(modules=[email_module]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                email="rotate@example.com",
                password="OldPassword123",
                email_verified=True,
            ),
        ]
    ) as context:
        client: TestClient = context.client

        client.post("/api/v1/auth/forgot-password", json={"email": "rotate@example.com"})
        first_token = _extract_token_from_email(email_module.emails[0].html_part)

        client.post("/api/v1/auth/forgot-password", json={"email": "rotate@example.com"})
        second_token = _extract_token_from_email(email_module.emails[1].html_part)

        # The superseded first token must no longer work.
        stale = client.post(
            "/api/v1/auth/reset-password",
            json={"token": first_token, "new_password": "NewPassword123"},
        )
        assert_that(stale.status_code, equal_to(status.HTTP_400_BAD_REQUEST))

        # The latest token still works.
        fresh = client.post(
            "/api/v1/auth/reset-password",
            json={"token": second_token, "new_password": "NewPassword123"},
        )
        assert_that(fresh.status_code, equal_to(status.HTTP_200_OK))


def test_logout_returns_success_message():
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.post("/api/v1/auth/logout")
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["message"], equal_to("Successfully logged out"))
