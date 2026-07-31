from uuid import uuid7

from hamcrest import assert_that, calling, equal_to, has_length, is_not, none, raises

from api.domains.users.exceptions import EmailTakenHTTPException
from api.domains.users.models import User, UserFilter
from api.domains.users.repository import UserRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.user import there_are_users


def test_i_can_save_new_user():
    with given([prepare_injector(), database_repo_is_ready(), database_is_clean()]) as context:
        repository: UserRepository = context.injector.get(UserRepository)

        with when("I save a user"):
            user = User(email="new_user@example.com", hashed_password="hashed_password")
            repository.save(user)

            with then("it should be persisted"):
                saved = repository.get_by_email("new_user@example.com")
                assert_that(saved, is_not(none()))
                assert saved is not None
                assert_that(saved.email, equal_to("new_user@example.com"))


def test_i_cannot_save_duplicate_email():
    with given([prepare_injector(), database_repo_is_ready(), database_is_clean()]) as context:
        repository: UserRepository = context.injector.get(UserRepository)

        with when("I save duplicate emails"):
            repository.save(User(email="dup_user@example.com", hashed_password="hashed_password"))

            with then("it should raise EmailTakenHTTPException"):
                assert_that(
                    calling(repository.save).with_args(
                        User(
                            email="dup_user@example.com",
                            hashed_password="hashed_password",
                        )
                    ),
                    raises(EmailTakenHTTPException),
                )


def test_find_all_in_organization():
    with given(
        [
            prepare_injector(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_an_organization(),
            there_are_users(
                [
                    {"email": "user1@example.com"},
                    {"email": "user2@example.com"},
                ]
            ),
        ]
    ) as context:
        repository: UserRepository = context.injector.get(UserRepository)

        with when("I list users"):
            users = repository.find_all(UserFilter(), organization_id=context.organization.id)

            with then("organization users should be returned"):
                assert_that(users, has_length(3))


def test_find_all_with_user_ids_filter():
    user_one = uuid7()
    user_two = uuid7()
    with given(
        [
            prepare_injector(),
            database_repo_is_ready(),
            database_is_clean(),
            there_are_users(
                [
                    {"id": user_one, "email": "filter1@example.com"},
                    {"id": user_two, "email": "filter2@example.com"},
                ]
            ),
        ]
    ) as context:
        repository: UserRepository = context.injector.get(UserRepository)

        users = repository.find_all(UserFilter(user_ids=[user_one]), organization_id=None)
        assert_that(users, has_length(1))
        assert_that(users[0].id, equal_to(user_one))


def test_find_all_by_ids_and_count():
    user_one = uuid7()
    user_two = uuid7()
    with given(
        [
            prepare_injector(),
            database_repo_is_ready(),
            database_is_clean(),
            there_are_users(
                [
                    {"id": user_one, "email": "count1@example.com"},
                    {"id": user_two, "email": "count2@example.com"},
                ]
            ),
        ]
    ) as context:
        repository: UserRepository = context.injector.get(UserRepository)

        found = repository.find_all_by_ids([user_one])
        assert_that(found, has_length(1))
        assert_that(found[0].id, equal_to(user_one))
        assert repository.count() >= 2
