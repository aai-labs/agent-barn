from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid7

import sqlalchemy as sa
from hamcrest import assert_that, calling, equal_to, has_items, raises
from sqlalchemy.exc import IntegrityError

from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

VALUE_SETTINGS_TABLE = "organization_value_settings"
OUTCOME_MINUTES_TABLE = "organization_outcome_minutes"

_GIVEN = [
    prepare_injector(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
]


def _engine(context) -> sa.Engine:
    return context.injector.get(PostgresRepositoryDelegate).engine


def _insert_rate(context, organization_id: UUID, rate: Decimal | None) -> None:
    now = datetime.now(UTC)
    with _engine(context).begin() as connection:
        connection.execute(
            sa.text(
                f"INSERT INTO {VALUE_SETTINGS_TABLE} (id, created_at, updated_at, organization_id, hourly_rate_usd) "
                "VALUES (:id, :now, :now, :organization_id, :rate)"
            ),
            {"id": uuid7(), "now": now, "organization_id": organization_id, "rate": rate},
        )


def _insert_minutes(context, organization_id: UUID, outcome_type: str, minutes: int) -> None:
    now = datetime.now(UTC)
    with _engine(context).begin() as connection:
        connection.execute(
            sa.text(
                f"INSERT INTO {OUTCOME_MINUTES_TABLE} "
                "(id, created_at, updated_at, organization_id, outcome_type, minutes_saved) "
                "VALUES (:id, :now, :now, :organization_id, :outcome_type, :minutes)"
            ),
            {
                "id": uuid7(),
                "now": now,
                "organization_id": organization_id,
                "outcome_type": outcome_type,
                "minutes": minutes,
            },
        )


def _count(context, table: str, organization_id: UUID) -> int:
    with _engine(context).connect() as connection:
        return connection.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE organization_id = :organization_id"),
            {"organization_id": organization_id},
        ).scalar_one()


def test_value_settings_tables_exist_after_migration():
    with given(_GIVEN) as context:
        with when("the migrated schema is inspected"):
            tables = sa.inspect(_engine(context)).get_table_names()

        with then("both value settings tables are present"):
            assert_that(tables, has_items(VALUE_SETTINGS_TABLE, OUTCOME_MINUTES_TABLE))


def test_hourly_rate_is_stored_with_two_decimal_places():
    with given(_GIVEN) as context:
        with when("a rate is written"):
            _insert_rate(context, context.organization.id, Decimal("42.5"))

        with then("it reads back as an exact two-place decimal"):
            with _engine(context).connect() as connection:
                stored = connection.execute(
                    sa.text(f"SELECT hourly_rate_usd FROM {VALUE_SETTINGS_TABLE} WHERE organization_id = :id"),
                    {"id": context.organization.id},
                ).scalar_one()
            assert_that(stored, equal_to(Decimal("42.50")))
            assert_that(str(stored), equal_to("42.50"))


def test_an_unset_hourly_rate_is_stored_as_null():
    with given(_GIVEN) as context:
        with when("a settings row is written without a rate"):
            _insert_rate(context, context.organization.id, None)

        with then("the row exists"):
            assert_that(_count(context, VALUE_SETTINGS_TABLE, context.organization.id), equal_to(1))


def test_a_negative_hourly_rate_is_rejected_by_the_database():
    with given(_GIVEN) as context:
        with then("the rate check constraint rejects it"):
            assert_that(
                calling(_insert_rate).with_args(context, context.organization.id, Decimal("-0.01")),
                raises(IntegrityError),
            )


def test_an_organization_has_at_most_one_value_settings_row():
    with given(_GIVEN) as context:
        _insert_rate(context, context.organization.id, Decimal("10.00"))

        with then("a second row for the same Organization is rejected"):
            assert_that(
                calling(_insert_rate).with_args(context, context.organization.id, Decimal("20.00")),
                raises(IntegrityError),
            )


def test_zero_minutes_saved_is_rejected_by_the_database():
    with given(_GIVEN) as context:
        with then("the minutes check constraint rejects it"):
            assert_that(
                calling(_insert_minutes).with_args(context, context.organization.id, "RECORD_CREATED", 0),
                raises(IntegrityError),
            )


def test_an_organization_has_at_most_one_override_per_outcome_type():
    with given(_GIVEN) as context:
        _insert_minutes(context, context.organization.id, "RECORD_CREATED", 5)

        with then("a second override for the same Outcome Type is rejected"):
            assert_that(
                calling(_insert_minutes).with_args(context, context.organization.id, "RECORD_CREATED", 7),
                raises(IntegrityError),
            )


def test_value_settings_are_deleted_with_their_organization():
    with given(_GIVEN) as context:
        organization_id = context.organization.id
        _insert_rate(context, organization_id, Decimal("10.00"))
        _insert_minutes(context, organization_id, "RECORD_CREATED", 5)

        with when("the Organization is deleted"):
            with _engine(context).begin() as connection:
                connection.execute(sa.text("DELETE FROM organization WHERE id = :id"), {"id": organization_id})

        with then("its value settings and overrides are gone"):
            assert_that(_count(context, VALUE_SETTINGS_TABLE, organization_id), equal_to(0))
            assert_that(_count(context, OUTCOME_MINUTES_TABLE, organization_id), equal_to(0))
