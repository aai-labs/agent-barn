from uuid import UUID

from hamcrest import assert_that, equal_to, instance_of, is_not
from sqlalchemy import text

from api.domains.analytics.repository import InstallationRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector
from api.tests.steps.database import database_repo_is_ready

_GIVEN = [prepare_injector(), database_repo_is_ready()]


def _stored_installation_ids(delegate: PostgresRepositoryDelegate) -> list[UUID]:
    with delegate.engine.connect() as connection:
        return list(connection.execute(text("SELECT id FROM installation")).scalars())


def _delete_installation(delegate: PostgresRepositoryDelegate) -> None:
    with delegate.engine.begin() as connection:
        connection.execute(text("DELETE FROM installation"))


def test_get_id_returns_the_stored_installation_id():
    with given(_GIVEN) as context:
        repository = InstallationRepository(delegate=context.postgres_delegate)

        installation_id = repository.get_id()

        assert_that([installation_id], equal_to(_stored_installation_ids(context.postgres_delegate)))


def test_get_id_is_stable_across_repository_instances():
    with given(_GIVEN) as context:
        first = InstallationRepository(delegate=context.postgres_delegate).get_id()
        second = InstallationRepository(delegate=context.postgres_delegate).get_id()

        assert_that(second, equal_to(first))


def test_get_id_recreates_a_missing_installation():
    with given(_GIVEN) as context:
        delegate = context.postgres_delegate
        previous = InstallationRepository(delegate=delegate).get_id()
        _delete_installation(delegate)

        recreated = InstallationRepository(delegate=delegate).get_id()

        assert_that(recreated, instance_of(UUID))
        assert_that(recreated, is_not(equal_to(previous)))
        assert_that(_stored_installation_ids(delegate), equal_to([recreated]))
