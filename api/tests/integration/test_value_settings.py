from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid7

import sqlalchemy as sa
from hamcrest import assert_that, calling, contains_inanyorder, empty, equal_to, has_items, has_length, none, raises
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.business_value.repository import ValueSettingsChangeResult, ValueSettingsRepository
from api.domains.events.catalog import ORGANIZATION_VALUE_SETTINGS_CHANGED
from api.domains.events.models import ActorIdentity, ActorIdentityType, EventDelivery, OutboxMessage
from api.domains.events.registry import DomainEventValidationError
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

VALUE_SETTINGS_TABLE = "organization_value_settings"
OUTCOME_MINUTES_TABLE = "organization_outcome_minutes"
ACTOR_DISPLAY = "Owner Person"
SUBJECT_DISPLAY = "Test Organization"

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


# --- persistence ------------------------------------------------------------------


def _repository(context) -> ValueSettingsRepository:
    return context.injector.get(ValueSettingsRepository)


def _actor(context) -> ActorIdentity:
    return ActorIdentity(
        type=ActorIdentityType.MEMBERSHIP,
        id=context.organization_user.id,
        organization_id=context.organization.id,
    )


def _save(
    context,
    *,
    hourly_rate: Decimal | None = None,
    rate_changed: bool = False,
    minute_changes: dict[str, int | None] | None = None,
    field_changes: dict[str, dict[str, str | None]] | None = None,
) -> ValueSettingsChangeResult:
    return _repository(context).save_with_event(
        context.organization.id,
        hourly_rate=hourly_rate,
        rate_changed=rate_changed,
        minute_changes=minute_changes or {},
        field_changes=field_changes or {"hourly_rate_usd": {"previous": None, "current": "1.00"}},
        actor=_actor(context),
        actor_display=ACTOR_DISPLAY,
        subject_display=SUBJECT_DISPLAY,
    )


def _change_events(context) -> list[OutboxMessage]:
    with Session(_engine(context)) as session:
        return list(
            session.exec(
                select(OutboxMessage).where(col(OutboxMessage.event_name) == ORGANIZATION_VALUE_SETTINGS_CHANGED)
            ).all()
        )


def _delivery_ids(context, event_id: UUID) -> list[UUID]:
    with Session(_engine(context)) as session:
        return list(session.exec(select(EventDelivery.id).where(col(EventDelivery.event_id) == event_id)).all())


def test_saving_value_settings_persists_the_rate_and_overrides():
    with given(_GIVEN) as context:
        with when("a rate and an override are saved"):
            _save(
                context,
                hourly_rate=Decimal("42.50"),
                rate_changed=True,
                minute_changes={"RECORD_CREATED": 12},
            )

        with then("both read back"):
            assert_that(_repository(context).get_hourly_rate(context.organization.id), equal_to(Decimal("42.50")))
            assert_that(
                _repository(context).get_minute_overrides(context.organization.id),
                equal_to({"RECORD_CREATED": 12}),
            )


def test_saving_value_settings_stages_one_change_event_with_its_deliveries():
    field_changes = {
        "hourly_rate_usd": {"previous": None, "current": "42.50"},
        "outcome_minutes.RECORD_CREATED": {"previous": None, "current": "12"},
    }
    with given(_GIVEN) as context:
        with when("a change is saved"):
            result = _save(
                context,
                hourly_rate=Decimal("42.50"),
                rate_changed=True,
                minute_changes={"RECORD_CREATED": 12},
                field_changes=field_changes,
            )

        with then("exactly one change event is staged, carrying the diff"):
            events = _change_events(context)
            assert_that(events, has_length(1))
            assert_that(events[0].organization_id, equal_to(context.organization.id))
            assert_that(
                events[0].payload,
                equal_to(
                    {
                        "organization_id": str(context.organization.id),
                        "field_changes": field_changes,
                        "actor_display": ACTOR_DISPLAY,
                        "subject_display": SUBJECT_DISPLAY,
                    }
                ),
            )
            assert_that(events[0].subject["type"], equal_to("ORGANIZATION"))

        with then("the returned delivery ids are the event's committed deliveries"):
            assert_that(result.delivery_ids, has_length(1))
            assert_that(result.delivery_ids, contains_inanyorder(*_delivery_ids(context, events[0].event_id)))


def test_saving_an_existing_override_replaces_its_minutes():
    with given(_GIVEN) as context:
        _save(context, minute_changes={"RECORD_CREATED": 12})

        with when("the same Outcome Type is saved again"):
            _save(context, minute_changes={"RECORD_CREATED": 30})

        with then("the override holds the new minutes and is still a single row"):
            assert_that(
                _repository(context).get_minute_overrides(context.organization.id),
                equal_to({"RECORD_CREATED": 30}),
            )
            assert_that(_count(context, OUTCOME_MINUTES_TABLE, context.organization.id), equal_to(1))


def test_saving_a_null_override_deletes_it():
    with given(_GIVEN) as context:
        _save(context, minute_changes={"RECORD_CREATED": 12, "COMMENT_POSTED": 9})

        with when("one override is saved as null"):
            _save(context, minute_changes={"RECORD_CREATED": None})

        with then("only the other override remains"):
            assert_that(
                _repository(context).get_minute_overrides(context.organization.id),
                equal_to({"COMMENT_POSTED": 9}),
            )


def test_saving_only_minutes_creates_no_settings_row():
    with given(_GIVEN) as context:
        with when("only an override is saved"):
            _save(context, minute_changes={"RECORD_CREATED": 12})

        with then("no rate row exists and the rate reads as unset"):
            assert_that(_count(context, VALUE_SETTINGS_TABLE, context.organization.id), equal_to(0))
            assert_that(_repository(context).get_hourly_rate(context.organization.id), none())


def test_saving_a_null_rate_clears_it():
    with given(_GIVEN) as context:
        _save(context, hourly_rate=Decimal("42.50"), rate_changed=True)

        with when("the rate is saved as null"):
            _save(context, hourly_rate=None, rate_changed=True)

        with then("the rate reads as unset"):
            assert_that(_repository(context).get_hourly_rate(context.organization.id), none())


def test_an_unset_organization_has_no_rate_and_no_overrides():
    with given(_GIVEN) as context:
        with then("both reads are empty"):
            assert_that(_repository(context).get_hourly_rate(context.organization.id), none())
            assert_that(_repository(context).get_minute_overrides(context.organization.id), equal_to({}))


def test_a_rejected_change_event_leaves_the_settings_unchanged():
    with given(_GIVEN) as context:
        with when("a save carries a change event the registry rejects"):

            def _save_with_invalid_event():
                _save(
                    context,
                    hourly_rate=Decimal("42.50"),
                    rate_changed=True,
                    minute_changes={"RECORD_CREATED": 12},
                    field_changes={"api_token": {"previous": None, "current": "x"}},
                )

        with then("the save fails"):
            assert_that(calling(_save_with_invalid_event), raises(DomainEventValidationError))

        with then("neither the settings nor the event were written"):
            assert_that(_count(context, VALUE_SETTINGS_TABLE, context.organization.id), equal_to(0))
            assert_that(_count(context, OUTCOME_MINUTES_TABLE, context.organization.id), equal_to(0))
            assert_that(_change_events(context), empty())
