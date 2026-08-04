from datetime import UTC, datetime, timedelta
from uuid import uuid7

from fastapi import HTTPException
from hamcrest import assert_that, calling, equal_to, is_not, none, raises

from api.domains.auth.models import CredentialClass, RefreshToken, TokenData
from api.domains.auth.repository import RefreshTokenRepository
from api.domains.auth.service import AuthService
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user


def test_i_can_save_and_get_refresh_token():
    user_id = uuid7()
    with given(
        [
            prepare_injector(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=user_id),
        ]
    ) as context:
        repository: RefreshTokenRepository = context.injector.get(RefreshTokenRepository)

        with when("I save a refresh token"):
            token = "sample_refresh_token"
            expires_at = datetime.now(UTC) + timedelta(days=15)
            refresh_token = RefreshToken(token=token, user_id=user_id, expires_at=expires_at, stamp="stamp")
            repository.save(refresh_token)

            with then("it should be retrievable"):
                saved = repository.get(token)
                assert saved is not None
                assert_that(saved.user_id, equal_to(user_id))


def test_i_can_create_access_token():
    user_id = uuid7()
    with given(
        [
            prepare_injector(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=user_id),
        ]
    ) as context:
        service: AuthService = context.injector.get(AuthService)

        with when("I create an access token"):
            access_token = service.create_access_token(
                TokenData(user_id=str(user_id), stamp="stamp", credential_class=CredentialClass.USER_SESSION)
            )

            with then("token should be generated"):
                assert_that(access_token, is_not(none()))


def test_i_cannot_verify_expired_refresh_token():
    user_id = uuid7()
    with given(
        [
            prepare_injector(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=user_id),
        ]
    ) as context:
        service: AuthService = context.injector.get(AuthService)
        repository: RefreshTokenRepository = context.injector.get(RefreshTokenRepository)

        with when("I verify an expired token"):
            token = "expired_refresh_token"
            expired = datetime.now(UTC) - timedelta(days=1)
            repository.save(RefreshToken(token=token, user_id=user_id, expires_at=expired, stamp="stamp"))

            with then("it should raise HTTPException"):
                assert_that(
                    calling(service.verify_refresh_token).with_args(token),
                    raises(HTTPException),
                )
