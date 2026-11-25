from uuid import uuid7

import pytest
from hamcrest import assert_that, equal_to
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from api.domains.llm_providers.access import ProviderNotOpen
from api.domains.llm_providers.lookup import LlmProviderAccessLookup
from api.domains.llm_providers.models import OPENROUTER_CONNECTION_ID, OPENROUTER_SLUG
from api.domains.llm_providers.repository import LlmProviderRepository
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization

LISTED = uuid7()
UNLISTED = uuid7()
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '200ms'"


def _setup():
    return [
        prepare_injector(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization(id=LISTED, name="Listed Org"),
        there_is_an_organization(id=UNLISTED, name="Unlisted Org"),
    ]


def _open_openrouter(context, mode, listed=()):
    with context.postgres_delegate.engine.begin() as connection:
        connection.execute(
            text("UPDATE llm_provider_connection SET organization_access = :mode WHERE id = :id"),
            {"mode": mode, "id": OPENROUTER_CONNECTION_ID},
        )
        for organization_id in listed:
            connection.execute(
                text(
                    "INSERT INTO llm_provider_connection_organization (connection_id, organization_id)"
                    " VALUES (:connection_id, :organization_id)"
                ),
                {"connection_id": OPENROUTER_CONNECTION_ID, "organization_id": organization_id},
            )


def _is_open(lookup, session, organization_id):
    try:
        lookup.require_open(session, OPENROUTER_SLUG, organization_id)
    except ProviderNotOpen:
        return False
    return True


@pytest.mark.parametrize(
    ("mode", "listed", "unlisted", "new"),
    [
        ("all", True, True, True),
        ("none", False, False, False),
        ("all_except", False, True, True),
        ("only", True, False, False),
    ],
)
def test_the_lookup_answers_from_the_stored_mode_and_list(mode, listed, unlisted, new):
    with given(_setup()) as context:
        _open_openrouter(context, mode, [LISTED])
        lookup = context.injector.get(LlmProviderAccessLookup)

        without_a_session = (lookup.can_use(OPENROUTER_SLUG, LISTED), lookup.can_use(OPENROUTER_SLUG, UNLISTED))
        with Session(context.postgres_delegate.engine) as session:
            in_a_session = (_is_open(lookup, session, LISTED), _is_open(lookup, session, UNLISTED))
            seed = lookup.initial_allowed_models(session, DEFAULT_MODEL)

    assert_that(without_a_session, equal_to((listed, unlisted)))
    assert_that(in_a_session, equal_to((listed, unlisted)))
    assert_that(seed, equal_to([DEFAULT_MODEL] if new else []))


def test_a_connection_that_does_not_exist_or_is_deleted_is_open_to_nobody():
    with given(_setup()) as context:
        with context.postgres_delegate.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO llm_provider_connection (id, created_at, updated_at, slug, name, provider_type,"
                    " deleted_at) VALUES (:id, now(), now(), 'anthropic', 'Anthropic', 'anthropic', now())"
                ),
                {"id": uuid7()},
            )
        lookup = context.injector.get(LlmProviderAccessLookup)

        answers = [lookup.can_use(slug, LISTED) for slug in ("anthropic", "mistral")]
        with Session(context.postgres_delegate.engine) as session, pytest.raises(ProviderNotOpen):
            lookup.require_open(session, "anthropic", LISTED)

    assert_that(answers, equal_to([False, False]))


def test_an_organization_side_write_waits_for_a_withdrawal_but_not_for_another_write():
    with given(_setup()) as context:
        engine = context.postgres_delegate.engine
        lookup = context.injector.get(LlmProviderAccessLookup)

        with Session(engine) as first, Session(engine) as second:
            lookup.require_open(first, OPENROUTER_SLUG, LISTED)
            second.connection().execute(text(LOCK_TIMEOUT))
            lookup.require_open(second, OPENROUTER_SLUG, LISTED)

        with Session(engine) as withdrawal:
            LlmProviderRepository._lock(withdrawal, OPENROUTER_SLUG)
            with Session(engine) as write:
                write.connection().execute(text(LOCK_TIMEOUT))
                with pytest.raises(OperationalError, match="lock timeout"):
                    lookup.require_open(write, OPENROUTER_SLUG, LISTED)
            withdrawal.rollback()

        with Session(engine) as write:
            write.connection().execute(text(LOCK_TIMEOUT))
            lookup.require_open(write, OPENROUTER_SLUG, LISTED)
