from datetime import UTC, datetime, timedelta
from uuid import uuid4, uuid7

from fastapi import status
from hamcrest import (
    assert_that,
    contains_string,
    equal_to,
    has_item,
    has_length,
    is_not,
    none,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from starlette.testclient import TestClient

from api.domains.events.constants import (
    EVENT_DELIVERY_PROCESSING_STALE_SECONDS,
    EVENT_DELIVERY_RECONCILIATION_ENQUEUED_STALE_SECONDS,
    EVENT_DELIVERY_RECONCILIATION_PENDING_GRACE_SECONDS,
)
from api.domains.events.models import (
    ActorIdentity,
    ActorIdentityType,
    EventDeliveryDeadLetterReason,
    EventScope,
    SubjectIdentity,
    SubjectIdentityType,
)
from api.domains.events.registry import DomainEventDefinition, DomainEventRegistry
from api.domains.events.repository import OutboxMessageRepository
from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.events import event_delivery_tables_are_clean
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

MONITOR_BASE = "/api/v1/platform/event-deliveries"


class _SamplePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    organization_id: str


class _PlatformSamplePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marker: str


def _registry(handler_names: tuple[str, ...] = ("handler.one", "handler.two")) -> DomainEventRegistry:
    registry = DomainEventRegistry()
    registry.register(
        DomainEventDefinition(
            event_name="monitor.sampled",
            schema_version=1,
            payload_model=_SamplePayload,
            handler_names=handler_names,
        )
    )
    return registry


def _platform_registry() -> DomainEventRegistry:
    registry = DomainEventRegistry()
    registry.register(
        DomainEventDefinition(
            event_name="monitor.platform.sampled",
            schema_version=1,
            payload_model=_PlatformSamplePayload,
            handler_names=("handler.platform",),
            event_scope=EventScope.PLATFORM,
        )
    )
    return registry


def _create_deliveries(
    repository: OutboxMessageRepository,
    registry: DomainEventRegistry,
    organization_id,
    *,
    event_name: str = "monitor.sampled",
):
    event = registry.build_event(
        event_name=event_name,
        schema_version=1,
        occurred_at=datetime.now(UTC),
        organization_id=organization_id,
        actor=ActorIdentity(type=ActorIdentityType.USER, id=uuid4(), organization_id=organization_id),
        subject=SubjectIdentity(type=SubjectIdentityType.AGENT, id=uuid4(), organization_id=organization_id),
        correlation_id=uuid4(),
        payload={"agent_id": str(uuid4()), "organization_id": str(organization_id)},
    )
    repository.create(event, registry)
    return sorted(repository.list_deliveries_for_event(event.event_id), key=lambda delivery: delivery.handler_name)


def _create_platform_delivery(repository: OutboxMessageRepository):
    registry = _platform_registry()
    event = registry.build_event(
        event_name="monitor.platform.sampled",
        schema_version=1,
        occurred_at=datetime.now(UTC),
        organization_id=None,
        actor=ActorIdentity(type=ActorIdentityType.USER, id=uuid4()),
        subject=SubjectIdentity(type=SubjectIdentityType.USER, id=uuid4()),
        correlation_id=uuid4(),
        payload={"marker": "platform"},
    )
    repository.create(event, registry)
    return repository.list_deliveries_for_event(event.event_id)[0]


def _set_created_at(delegate: PostgresRepositoryDelegate, delivery_id, created_at: datetime) -> None:
    with delegate.engine.begin() as connection:
        connection.execute(
            text("UPDATE event_delivery SET created_at = :created_at WHERE id = :id"),
            {"created_at": created_at, "id": delivery_id},
        )


def _set_last_error(delegate: PostgresRepositoryDelegate, delivery_id, last_error: str) -> None:
    with delegate.engine.begin() as connection:
        connection.execute(
            text("UPDATE event_delivery SET last_error = :last_error WHERE id = :id"),
            {"last_error": last_error, "id": delivery_id},
        )


def _null_enqueued_at(delegate: PostgresRepositoryDelegate, delivery_id) -> None:
    with delegate.engine.begin() as connection:
        connection.execute(
            text("UPDATE event_delivery SET enqueued_at = NULL WHERE id = :id"),
            {"id": delivery_id},
        )


def _auth_headers(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _base_given(is_platform_admin: bool = True):
    return [
        prepare_injector(),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        event_delivery_tables_are_clean(),
        there_is_a_user(
            id=uuid7(),
            email=f"event-monitor-{uuid7()}@example.com",
            is_platform_admin=is_platform_admin,
        ),
        there_is_an_access_token_for_user(),
    ]


def test_unauthenticated_caller_cannot_access_summary():
    with given(_base_given()) as context:
        client: TestClient = context.client

        response = client.get(f"{MONITOR_BASE}/summary")

        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_non_platform_admin_cannot_access_summary():
    with given(_base_given(is_platform_admin=False)) as context:
        client: TestClient = context.client

        response = client.get(f"{MONITOR_BASE}/summary", headers=_auth_headers(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_non_platform_admin_cannot_list_deliveries():
    with given(_base_given(is_platform_admin=False)) as context:
        client: TestClient = context.client

        response = client.get(MONITOR_BASE, headers=_auth_headers(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_non_platform_admin_cannot_list_event_types():
    with given(_base_given(is_platform_admin=False)) as context:
        client: TestClient = context.client

        response = client.get(f"{MONITOR_BASE}/event-types", headers=_auth_headers(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_summary_reports_zero_counts_for_all_statuses_when_empty():
    with given(_base_given()) as context:
        client: TestClient = context.client

        response = client.get(f"{MONITOR_BASE}/summary", headers=_auth_headers(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["total_count"], equal_to(0))
        assert_that(
            body["status_counts"],
            equal_to({"pending": 0, "enqueued": 0, "processing": 0, "succeeded": 0, "dead_lettered": 0}),
        )
        for state in ("pending", "enqueued", "processing"):
            assert_that(body[state]["count"], equal_to(0))
            assert_that(body[state]["stale_count"], equal_to(0))
            assert_that(body[state]["unknown_age_count"], equal_to(0))
            assert_that(body[state]["oldest_age_seconds"], none())


def test_summary_marks_stale_pending_by_created_at_using_reconciler_threshold():
    with given(_base_given()) as context:
        client: TestClient = context.client
        delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
        repository: OutboxMessageRepository = context.injector.get(OutboxMessageRepository)
        organization_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        organization = Organization(name="Stale Pending Org")
        organization_repository.save(organization)
        registry = _registry(handler_names=("handler.one",))

        stale_delivery = _create_deliveries(repository, registry, organization.id)[0]
        old_created_at = datetime.now(UTC) - timedelta(seconds=EVENT_DELIVERY_RECONCILIATION_PENDING_GRACE_SECONDS + 30)
        _set_created_at(delegate, stale_delivery.id, old_created_at)

        fresh_delivery = _create_deliveries(repository, registry, organization.id)[0]

        response = client.get(f"{MONITOR_BASE}/summary", headers=_auth_headers(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["pending"]["count"], equal_to(2))
        assert_that(body["pending"]["stale_count"], equal_to(1))
        assert_that(body["pending"]["unknown_age_count"], equal_to(0))
        assert_that(
            body["pending"]["stale_threshold_seconds"], equal_to(EVENT_DELIVERY_RECONCILIATION_PENDING_GRACE_SECONDS)
        )
        assert_that(body["pending"]["oldest_age_seconds"], is_not(none()))
        assert_that(fresh_delivery.id, is_not(none()))


def test_summary_treats_missing_state_timestamp_as_unknown_not_created_at_fallback():
    with given(_base_given()) as context:
        client: TestClient = context.client
        delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
        repository: OutboxMessageRepository = context.injector.get(OutboxMessageRepository)
        organization_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        organization = Organization(name="Unknown Age Org")
        organization_repository.save(organization)
        registry = _registry(handler_names=("handler.one",))

        delivery = _create_deliveries(repository, registry, organization.id)[0]
        repository.mark_delivery_enqueued(delivery.id)
        # Simulate a data anomaly where the ENQUEUED state's clock is missing; this
        # must surface as unknown age, never silently fall back to created_at.
        _null_enqueued_at(delegate, delivery.id)

        response = client.get(f"{MONITOR_BASE}/summary", headers=_auth_headers(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["enqueued"]["count"], equal_to(1))
        assert_that(body["enqueued"]["unknown_age_count"], equal_to(1))
        assert_that(body["enqueued"]["stale_count"], equal_to(0))
        assert_that(body["enqueued"]["oldest_age_seconds"], none())
        assert_that(
            body["enqueued"]["stale_threshold_seconds"], equal_to(EVENT_DELIVERY_RECONCILIATION_ENQUEUED_STALE_SECONDS)
        )

        explorer_response = client.get(MONITOR_BASE, headers=_auth_headers(context))
        item = explorer_response.json()["items"][0]
        assert_that(item["status_since"], none())


def test_summary_reflects_processing_stale_threshold_and_dead_letter_count():
    with given(_base_given()) as context:
        client: TestClient = context.client
        repository: OutboxMessageRepository = context.injector.get(OutboxMessageRepository)
        organization_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        organization = Organization(name="Processing Org")
        organization_repository.save(organization)
        registry = _registry(handler_names=("handler.one", "handler.two"))

        processing_delivery, dead_delivery = _create_deliveries(repository, registry, organization.id)
        repository.mark_delivery_enqueued(processing_delivery.id)
        repository.claim_delivery(processing_delivery.id)
        repository.mark_delivery_enqueued(dead_delivery.id)
        repository.claim_delivery(dead_delivery.id)
        repository.mark_delivery_dead_lettered(
            dead_delivery.id,
            reason=EventDeliveryDeadLetterReason.TERMINAL_HANDLER_ERROR,
            error="boom",
        )

        response = client.get(f"{MONITOR_BASE}/summary", headers=_auth_headers(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["processing"]["count"], equal_to(1))
        assert_that(body["processing"]["stale_threshold_seconds"], equal_to(EVENT_DELIVERY_PROCESSING_STALE_SECONDS))
        assert_that(body["status_counts"]["dead_lettered"], equal_to(1))
        assert_that(body["total_count"], equal_to(2))


def test_explorer_orders_newest_first_by_default_and_supports_oldest_first():
    with given(_base_given()) as context:
        client: TestClient = context.client
        delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
        repository: OutboxMessageRepository = context.injector.get(OutboxMessageRepository)
        organization_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        organization = Organization(name="Order Org")
        organization_repository.save(organization)
        registry = _registry(handler_names=("handler.one",))

        base = datetime.now(UTC) - timedelta(hours=1)
        ids = []
        for offset in range(3):
            delivery = _create_deliveries(repository, registry, organization.id)[0]
            _set_created_at(delegate, delivery.id, base + timedelta(minutes=offset))
            ids.append(str(delivery.id))

        newest_first = client.get(MONITOR_BASE, headers=_auth_headers(context))
        assert_that(newest_first.status_code, equal_to(status.HTTP_200_OK))
        newest_items = [item["id"] for item in newest_first.json()["items"]]
        assert_that(newest_items, equal_to(list(reversed(ids))))

        oldest_first = client.get(f"{MONITOR_BASE}?sort=OLDEST_FIRST", headers=_auth_headers(context))
        oldest_items = [item["id"] for item in oldest_first.json()["items"]]
        assert_that(oldest_items, equal_to(ids))


def test_explorer_paginates_deterministically_without_duplicates():
    with given(_base_given()) as context:
        client: TestClient = context.client
        repository: OutboxMessageRepository = context.injector.get(OutboxMessageRepository)
        organization_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        organization = Organization(name="Pagination Org")
        organization_repository.save(organization)
        registry = _registry(handler_names=("handler.one",))

        for _ in range(5):
            _create_deliveries(repository, registry, organization.id)

        seen: list[str] = []
        page = 1
        while True:
            response = client.get(f"{MONITOR_BASE}?page={page}&page_size=2", headers=_auth_headers(context))
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            seen.extend(item["id"] for item in body["items"])
            if page * 2 >= body["total"]:
                break
            page += 1

        assert_that(seen, has_length(5))
        assert_that(len(set(seen)), equal_to(5))


def test_explorer_filters_by_status_organization_and_event_name():
    with given(_base_given()) as context:
        client: TestClient = context.client
        repository: OutboxMessageRepository = context.injector.get(OutboxMessageRepository)
        organization_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        org_a = Organization(name="Filter Org A")
        org_b = Organization(name="Filter Org B")
        organization_repository.save(org_a)
        organization_repository.save(org_b)
        registry = _registry(handler_names=("handler.one",))

        delivery_a = _create_deliveries(repository, registry, org_a.id, event_name="monitor.sampled")[0]
        _create_deliveries(repository, registry, org_b.id, event_name="monitor.sampled")
        repository.mark_delivery_enqueued(delivery_a.id)

        by_org = client.get(f"{MONITOR_BASE}?organization_id={org_a.id}", headers=_auth_headers(context))
        org_items = by_org.json()["items"]
        assert_that(org_items, has_length(1))
        assert_that(org_items[0]["organization_id"], equal_to(str(org_a.id)))

        by_status = client.get(f"{MONITOR_BASE}?status=ENQUEUED", headers=_auth_headers(context))
        status_items = by_status.json()["items"]
        assert_that(status_items, has_length(1))
        assert_that(status_items[0]["id"], equal_to(str(delivery_a.id)))

        by_event_name = client.get(f"{MONITOR_BASE}?event_name=monitor.sampled", headers=_auth_headers(context))
        assert_that(by_event_name.json()["total"], equal_to(2))

        by_missing_event_name = client.get(f"{MONITOR_BASE}?event_name=does.not.exist", headers=_auth_headers(context))
        assert_that(by_missing_event_name.json()["total"], equal_to(0))


def test_explorer_includes_platform_deliveries_without_an_organization():
    with given(_base_given()) as context:
        client: TestClient = context.client
        repository: OutboxMessageRepository = context.injector.get(OutboxMessageRepository)

        delivery = _create_platform_delivery(repository)

        response = client.get(MONITOR_BASE, headers=_auth_headers(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["total"], equal_to(1))
        assert_that(body["items"][0]["id"], equal_to(str(delivery.id)))
        assert_that(body["items"][0]["organization_id"], none())
        assert_that(body["items"][0]["organization_name"], none())


def test_explorer_created_at_range_filter():
    with given(_base_given()) as context:
        client: TestClient = context.client
        delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
        repository: OutboxMessageRepository = context.injector.get(OutboxMessageRepository)
        organization_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        organization = Organization(name="Date Range Org")
        organization_repository.save(organization)
        registry = _registry(handler_names=("handler.one",))

        old_delivery = _create_deliveries(repository, registry, organization.id)[0]
        _set_created_at(delegate, old_delivery.id, datetime(2020, 1, 1, tzinfo=UTC))
        recent_delivery = _create_deliveries(repository, registry, organization.id)[0]

        response = client.get(
            f"{MONITOR_BASE}?created_from=2025-01-01T00:00:00Z",
            headers=_auth_headers(context),
        )

        items = response.json()["items"]
        assert_that([item["id"] for item in items], equal_to([str(recent_delivery.id)]))


def test_explorer_search_is_exact_match_for_delivery_and_event_id():
    with given(_base_given()) as context:
        client: TestClient = context.client
        repository: OutboxMessageRepository = context.injector.get(OutboxMessageRepository)
        organization_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        organization = Organization(name="Search Id Org")
        organization_repository.save(organization)
        registry = _registry(handler_names=("handler.one",))

        delivery = _create_deliveries(repository, registry, organization.id)[0]
        _create_deliveries(repository, registry, organization.id)

        by_delivery_id = client.get(f"{MONITOR_BASE}?search={delivery.id}", headers=_auth_headers(context))
        assert_that([item["id"] for item in by_delivery_id.json()["items"]], equal_to([str(delivery.id)]))

        by_event_id = client.get(f"{MONITOR_BASE}?search={delivery.event_id}", headers=_auth_headers(context))
        assert_that([item["id"] for item in by_event_id.json()["items"]], equal_to([str(delivery.id)]))


def test_explorer_search_is_case_insensitive_prefix_match_for_org_event_and_handler_name():
    with given(_base_given()) as context:
        client: TestClient = context.client
        repository: OutboxMessageRepository = context.injector.get(OutboxMessageRepository)
        organization_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        organization = Organization(name="Acme Corp")
        organization_repository.save(organization)
        registry = _registry(handler_names=("audit.projection",))

        delivery = _create_deliveries(repository, registry, organization.id)[0]

        by_org_prefix = client.get(f"{MONITOR_BASE}?search=acme", headers=_auth_headers(context))
        assert_that([item["id"] for item in by_org_prefix.json()["items"]], equal_to([str(delivery.id)]))

        by_event_prefix = client.get(f"{MONITOR_BASE}?search=MONITOR.SAM", headers=_auth_headers(context))
        assert_that([item["id"] for item in by_event_prefix.json()["items"]], equal_to([str(delivery.id)]))

        by_handler_prefix = client.get(f"{MONITOR_BASE}?search=AUDIT.pro", headers=_auth_headers(context))
        assert_that([item["id"] for item in by_handler_prefix.json()["items"]], equal_to([str(delivery.id)]))

        # A middle-of-string match must not hit (search is prefix-only, not substring).
        by_suffix = client.get(f"{MONITOR_BASE}?search=corp", headers=_auth_headers(context))
        assert_that(by_suffix.json()["items"], equal_to([]))


def test_explorer_search_does_not_match_last_error():
    with given(_base_given()) as context:
        client: TestClient = context.client
        delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
        repository: OutboxMessageRepository = context.injector.get(OutboxMessageRepository)
        organization_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        organization = Organization(name="Error Search Org")
        organization_repository.save(organization)
        registry = _registry(handler_names=("handler.one",))

        delivery = _create_deliveries(repository, registry, organization.id)[0]
        _set_last_error(delegate, delivery.id, "unique-marker-error-text")

        response = client.get(f"{MONITOR_BASE}?search=unique-marker", headers=_auth_headers(context))

        assert_that(response.json()["items"], equal_to([]))


def test_explorer_redacts_and_bounds_last_error_at_read_boundary():
    with given(_base_given()) as context:
        client: TestClient = context.client
        delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
        repository: OutboxMessageRepository = context.injector.get(OutboxMessageRepository)
        organization_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        organization = Organization(name="Redaction Org")
        organization_repository.save(organization)
        registry = _registry(handler_names=("handler.one",))

        delivery = _create_deliveries(repository, registry, organization.id)[0]
        # Simulate a stored value that bypassed write-time bounding, proving the read
        # path re-applies redaction as defense in depth rather than trusting storage.
        _set_last_error(delegate, delivery.id, "leaked api_key=super-secret-value")

        response = client.get(f"{MONITOR_BASE}?status=PENDING", headers=_auth_headers(context))

        item = response.json()["items"][0]
        assert_that(item["last_error"], is_not(contains_string("super-secret-value")))
        assert_that(item["last_error"], equal_to("Event delivery error contained sensitive details and was redacted"))


def test_explorer_response_excludes_payload_and_identity_fields():
    with given(_base_given()) as context:
        client: TestClient = context.client
        repository: OutboxMessageRepository = context.injector.get(OutboxMessageRepository)
        organization_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        organization = Organization(name="Payload Safety Org")
        organization_repository.save(organization)
        registry = _registry(handler_names=("handler.one",))
        _create_deliveries(repository, registry, organization.id)

        response = client.get(MONITOR_BASE, headers=_auth_headers(context))

        item = response.json()["items"][0]
        for forbidden_key in (
            "payload",
            "actor",
            "subject",
            "correlation_id",
            "causation_id",
        ):
            assert_that(forbidden_key in item, equal_to(False))


def test_status_since_derives_from_the_matching_state_clock():
    with given(_base_given()) as context:
        client: TestClient = context.client
        repository: OutboxMessageRepository = context.injector.get(OutboxMessageRepository)
        organization_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        organization = Organization(name="Status Since Org")
        organization_repository.save(organization)
        registry = _registry(handler_names=("handler.one",))

        delivery = _create_deliveries(repository, registry, organization.id)[0]
        repository.mark_delivery_succeeded(delivery.id)

        response = client.get(MONITOR_BASE, headers=_auth_headers(context))

        item = response.json()["items"][0]
        assert_that(item["status"], equal_to("SUCCEEDED"))
        assert_that(item["status_since"], equal_to(item["completed_at"]))


def test_event_types_endpoint_excludes_handlerless_event_definitions():
    with given(_base_given()) as context:
        client: TestClient = context.client

        response = client.get(f"{MONITOR_BASE}/event-types", headers=_auth_headers(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        event_names = [entry["event_name"] for entry in response.json()]
        # organization.role.changed has a registered handler and must be offered as a
        # filter option; agent.created has zero handlers and can never produce an
        # Event Delivery, so it must not appear.
        assert_that(event_names, has_item("organization.role.changed"))
        assert_that("agent.created" in event_names, equal_to(False))
