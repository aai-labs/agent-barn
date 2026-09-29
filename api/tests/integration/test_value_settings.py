from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid7

import pytest
import sqlalchemy as sa
from fastapi import status
from hamcrest import (
    assert_that,
    calling,
    contains_exactly,
    contains_inanyorder,
    empty,
    equal_to,
    has_entries,
    has_items,
    has_length,
    is_not,
    none,
    raises,
)
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.business_value.catalogue import DEFAULT_MINUTES, OutcomeType
from api.domains.business_value.repository import ValueSettingsChangeResult, ValueSettingsRepository
from api.domains.events.catalog import ORGANIZATION_VALUE_SETTINGS_CHANGED
from api.domains.events.models import ActorIdentity, ActorIdentityType, EventDelivery, OutboxMessage
from api.domains.events.processor import EventDeliveryProcessor
from api.domains.events.registry import DomainEventValidationError
from api.domains.events.repository import OutboxMessageRepository
from api.domains.events.security_audit import SecurityAuditRepository
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector
from api.tests.steps.agent import use_org_for_auth
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

VALUE_SETTINGS_TABLE = "organization_value_settings"
OUTCOME_MINUTES_TABLE = "organization_outcome_minutes"
ACTOR_DISPLAY = "Owner Person"
SUBJECT_DISPLAY = "Test Organization"
SETTINGS_URL = "/api/v1/organizations/{organization_id}/value-settings"
STALE_OUTCOME_TYPE = "OUTCOME_REMOVED_FROM_CATALOGUE"

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


# --- API --------------------------------------------------------------------------

_API_GIVEN = [
    prepare_injector(),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _url(organization_id: UUID) -> str:
    return SETTINGS_URL.format(organization_id=organization_id)


def _there_is_an_actor_in_the_organization(role: OrganizationRole, email: str):
    def step(context):
        there_is_a_user(email=email, role=role)(context)
        there_is_an_access_token_for_user()(context)

    return step


def _there_is_an_actor_in_another_organization(email: str):
    def step(context):
        context.target_organization_id = context.organization.id
        there_is_a_user(email=email, organization_id=uuid7(), role=OrganizationRole.OWNER)(context)
        there_is_an_access_token_for_user()(context)

    return step


def _put(context, body: dict):
    return context.client.put(SETTINGS_URL, json=body, headers=_auth(context))


def _row(body: dict, outcome_type: OutcomeType) -> dict:
    return next(row for row in body["outcome_minutes"] if row["outcome_type"] == outcome_type.value)


def test_a_new_organization_reads_the_catalogue_defaults_and_no_rate():
    with given(_API_GIVEN) as context:
        with when("the Owner reads value settings that were never set"):
            response = context.client.get(SETTINGS_URL, headers=_auth(context))

        with then("every catalogue Outcome Type is listed at its default, with no rate"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["hourly_rate_usd"], none())
            assert_that(
                body["outcome_minutes"],
                contains_exactly(
                    *[
                        has_entries(
                            outcome_type=outcome.value,
                            default_minutes=minutes,
                            override_minutes=None,
                            effective_minutes=minutes,
                            source="default",
                        )
                        for outcome, minutes in DEFAULT_MINUTES.items()
                    ]
                ),
            )


def test_the_owner_sets_a_rate_and_an_override():
    with given(_API_GIVEN) as context:
        with when("the Owner saves a rate and one override"):
            response = _put(context, {"hourly_rate_usd": 42.5, "outcome_minutes": {"RECORD_CREATED": 12}})

        with then("the read reports both, and the other types keep their defaults"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["hourly_rate_usd"], equal_to(42.5))
            assert_that(
                _row(body, OutcomeType.RECORD_CREATED),
                has_entries(
                    default_minutes=DEFAULT_MINUTES[OutcomeType.RECORD_CREATED],
                    override_minutes=12,
                    effective_minutes=12,
                    source="override",
                ),
            )
            assert_that(_row(body, OutcomeType.COMMENT_POSTED), has_entries(source="default", override_minutes=None))


def test_an_admin_can_read_and_change_value_settings():
    with given(
        [*_API_GIVEN, _there_is_an_actor_in_the_organization(OrganizationRole.ADMIN, "admin-value@example.com")]
    ) as context:
        with when("an Admin reads and then changes the rate"):
            read = context.client.get(SETTINGS_URL, headers=_auth(context))
            write = _put(context, {"hourly_rate_usd": 30})

        with then("both succeed"):
            assert_that(read.status_code, equal_to(status.HTTP_200_OK))
            assert_that(write.status_code, equal_to(status.HTTP_200_OK))
            assert_that(write.json()["hourly_rate_usd"], equal_to(30.0))


def test_a_member_cannot_read_or_change_value_settings():
    with given(
        [*_API_GIVEN, _there_is_an_actor_in_the_organization(OrganizationRole.MEMBER, "member-value@example.com")]
    ) as context:
        with when("a Member reads and changes value settings"):
            read = context.client.get(SETTINGS_URL, headers=_auth(context))
            write = _put(context, {"hourly_rate_usd": 30})

        with then("both are forbidden and nothing is recorded"):
            assert_that(read.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(write.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(_change_events(context), empty())


def test_a_non_member_cannot_read_or_change_value_settings():
    with given([*_API_GIVEN, _there_is_an_actor_in_another_organization("outsider-value@example.com")]) as context:
        with when("an Owner of another Organization targets this one"):
            read = context.client.get(_url(context.target_organization_id), headers=_auth(context))
            write = context.client.put(
                _url(context.target_organization_id), json={"hourly_rate_usd": 30}, headers=_auth(context)
            )

        with then("both are forbidden"):
            assert_that(read.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(write.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_platform_admin_without_membership_cannot_read_value_settings():
    super_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=super_id, email="super-value@example.com", is_platform_admin=True),
            there_is_an_organization_with_user_and_access_token(email="owner-super-value@example.com"),
            use_org_for_auth(),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        with when("a Platform Administrator with no Membership reads value settings"):
            response = context.client.get(SETTINGS_URL, headers=_auth(context))

        with then("it is forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_value_settings_require_authentication():
    with given(_API_GIVEN) as context:
        with when("an unauthenticated caller reads and changes value settings"):
            read = context.client.get(SETTINGS_URL)
            write = context.client.put(SETTINGS_URL, json={"hourly_rate_usd": 30})

        with then("both are rejected"):
            assert_that(read.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
            assert_that(write.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_a_change_records_one_event_with_its_field_changes():
    with given(_API_GIVEN) as context:
        with when("the Owner saves a rate and an override"):
            _put(context, {"hourly_rate_usd": 42.5, "outcome_minutes": {"RECORD_CREATED": 12}})

        with then("one change event carries both transitions as strings"):
            events = _change_events(context)
            assert_that(events, has_length(1))
            assert_that(
                events[0].payload["field_changes"],
                equal_to(
                    {
                        "hourly_rate_usd": {"previous": None, "current": "42.50"},
                        "outcome_minutes.RECORD_CREATED": {"previous": None, "current": "12"},
                    }
                ),
            )
            assert_that(events[0].payload["actor_display"], is_not(empty()))
            assert_that(events[0].payload["subject_display"], equal_to(context.organization.name))


def test_saving_unchanged_value_settings_records_nothing():
    body = {"hourly_rate_usd": 42.5, "outcome_minutes": {"RECORD_CREATED": 12}}
    with given(_API_GIVEN) as context:
        _put(context, body)

        with when("the Owner saves the same values again, with the rate spelled differently"):
            response = _put(context, {**body, "hourly_rate_usd": "42.50"})

        with then("the save succeeds and no second event is recorded"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_change_events(context), has_length(1))


def test_an_empty_update_changes_nothing_and_records_nothing():
    with given(_API_GIVEN) as context:
        with when("the Owner sends an empty update"):
            response = _put(context, {})

        with then("the defaults are returned and no event is recorded"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["hourly_rate_usd"], none())
            assert_that(_change_events(context), empty())


def test_omitting_the_rate_leaves_it_unchanged():
    with given(_API_GIVEN) as context:
        _put(context, {"hourly_rate_usd": 42.5})

        with when("the Owner changes only an override"):
            response = _put(context, {"outcome_minutes": {"RECORD_CREATED": 12}})

        with then("the rate is kept and only the override is recorded as changed"):
            assert_that(response.json()["hourly_rate_usd"], equal_to(42.5))
            assert_that(
                _change_events(context)[-1].payload["field_changes"],
                equal_to({"outcome_minutes.RECORD_CREATED": {"previous": None, "current": "12"}}),
            )


def test_a_null_rate_clears_it():
    with given(_API_GIVEN) as context:
        _put(context, {"hourly_rate_usd": 42.5})

        with when("the Owner saves a null rate"):
            response = _put(context, {"hourly_rate_usd": None})

        with then("the rate is unset and the change is recorded"):
            assert_that(response.json()["hourly_rate_usd"], none())
            assert_that(
                _change_events(context)[-1].payload["field_changes"],
                equal_to({"hourly_rate_usd": {"previous": "42.50", "current": None}}),
            )


def test_a_null_override_reverts_to_the_default():
    with given(_API_GIVEN) as context:
        _put(context, {"outcome_minutes": {"RECORD_CREATED": 12}})

        with when("the Owner saves the override as null"):
            response = _put(context, {"outcome_minutes": {"RECORD_CREATED": None}})

        with then("the Outcome Type is back on its default and the revert is recorded"):
            assert_that(
                _row(response.json(), OutcomeType.RECORD_CREATED),
                has_entries(
                    override_minutes=None,
                    effective_minutes=DEFAULT_MINUTES[OutcomeType.RECORD_CREATED],
                    source="default",
                ),
            )
            assert_that(
                _change_events(context)[-1].payload["field_changes"],
                equal_to({"outcome_minutes.RECORD_CREATED": {"previous": "12", "current": None}}),
            )


def test_a_stored_override_outside_the_catalogue_is_ignored_on_read():
    with given(_API_GIVEN) as context:
        _insert_minutes(context, context.organization.id, STALE_OUTCOME_TYPE, 30)

        with when("the Owner reads value settings"):
            response = context.client.get(SETTINGS_URL, headers=_auth(context))

        with then("only catalogue Outcome Types are listed"):
            outcome_types = [row["outcome_type"] for row in response.json()["outcome_minutes"]]
            assert_that(outcome_types, equal_to([outcome.value for outcome in DEFAULT_MINUTES]))


@pytest.mark.parametrize(
    "body",
    [
        {"outcome_minutes": {"NOT_AN_OUTCOME_TYPE": 5}},
        {"outcome_minutes": {"record_created": 5}},
        {"outcome_minutes": {"RECORD_CREATED": 0}},
        {"outcome_minutes": {"RECORD_CREATED": -1}},
        {"outcome_minutes": {"RECORD_CREATED": 1441}},
        {"outcome_minutes": {"RECORD_CREATED": "5"}},
        {"outcome_minutes": {"RECORD_CREATED": 5.0}},
        {"outcome_minutes": {"RECORD_CREATED": True}},
        {"hourly_rate_usd": -0.01},
        {"hourly_rate_usd": 10000.01},
        {"hourly_rate_usd": 12.345},
        {"unexpected": 1},
    ],
    ids=[
        "unknown-outcome-type",
        "lowercase-outcome-type",
        "zero-minutes",
        "negative-minutes",
        "minutes-above-bound",
        "string-minutes",
        "float-minutes",
        "boolean-minutes",
        "negative-rate",
        "rate-above-bound",
        "rate-with-three-decimals",
        "unknown-field",
    ],
)
def test_an_invalid_update_is_rejected_and_records_nothing(body):
    with given(_API_GIVEN) as context:
        with when("the Owner sends an invalid update"):
            response = _put(context, body)

        with then("it is rejected as unprocessable and nothing is stored"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))
            assert_that(_count(context, VALUE_SETTINGS_TABLE, context.organization.id), equal_to(0))
            assert_that(_count(context, OUTCOME_MINUTES_TABLE, context.organization.id), equal_to(0))
            assert_that(_change_events(context), empty())


def test_a_change_projects_to_a_durable_security_audit_record():
    with given(_API_GIVEN) as context:
        _put(context, {"hourly_rate_usd": 42.5})
        event = _change_events(context)[0]
        outbox_repository = context.injector.get(OutboxMessageRepository)
        delivery = outbox_repository.list_deliveries_for_event(event.event_id)[0]

        with when("the delivery is processed"):
            outbox_repository.mark_delivery_enqueued(delivery.id)
            processed = context.injector.get(EventDeliveryProcessor).process(delivery.id)

        with then("a security audit record holds the change"):
            assert_that(processed, equal_to(True))
            record = context.injector.get(SecurityAuditRepository).get_by_event_id(event.event_id)
            assert_that(record, is_not(none()))
            assert record is not None
            assert_that(record.action, equal_to(ORGANIZATION_VALUE_SETTINGS_CHANGED))
            assert_that(record.organization_id, equal_to(context.organization.id))
            assert_that(
                record.details["field_changes"],
                equal_to({"hourly_rate_usd": {"previous": None, "current": "42.50"}}),
            )
