"""Local dev fixture generator for the Platform Event Delivery Monitor (AF-247).

Not part of the production/test code path. Populates real Outbox Message and Event
Delivery rows (through the same registry/repository the app uses) so the monitor UI
has realistic data to browse against a local dev database. Safe to re-run; each run
adds another batch on top of whatever already exists.

Usage (from `api/`, with the dev stack's Postgres reachable via DB_CONNECTION_URL):
    uv run python -m api.scripts.seed_event_delivery_monitor_fixtures [--count 200]
"""

import argparse
import random
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlmodel import Session, select

from api.core.config import get_config
from api.domains.events.catalog import (
    AGENT_ACCESS_GRANTED,
    AGENT_ACCESS_REVOKED,
    AGENT_GENERAL_ACCESS_CHANGED,
    AGENT_STARTED,
    AGENT_STOPPED,
    EVENT_REGISTRY,
    ORGANIZATION_ROLE_CHANGED,
)
from api.domains.events.models import (
    ActorIdentity,
    ActorIdentityType,
    EventDelivery,
    EventDeliveryDeadLetterReason,
    SubjectIdentity,
    SubjectIdentityType,
)
from api.domains.events.repository import OutboxMessageRepository
from api.domains.organizations.models import Organization
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

ORG_NAMES = [
    "Acme Robotics",
    "Globex Corporation",
    "Initech",
    "Umbrella Labs",
    "Stark Industries",
    "Wayne Enterprises",
]

ORGANIZATION_ROLES = ["MEMBER", "ADMIN", "OWNER"]
PLATFORMS = ["slack", "telegram", "discord"]
RUNTIMES = ["openclaw", "hermes"]
AGENT_NAMES = ["Support Bot", "Release Notes Agent", "Standup Reporter", "Incident Triager", "Onboarding Guide"]

DEAD_LETTER_REASONS = list(EventDeliveryDeadLetterReason)
DEAD_LETTER_ERRORS = {
    EventDeliveryDeadLetterReason.RETRY_EXHAUSTED: "Handler raised RetryableEventHandlerError on all 20 attempts",
    EventDeliveryDeadLetterReason.TERMINAL_HANDLER_ERROR: (
        "Handler raised TerminalEventHandlerError: downstream audit sink returned 400 Bad Request"
    ),
    EventDeliveryDeadLetterReason.UNKNOWN_HANDLER: "No Event Handler is registered with this stable name",
    EventDeliveryDeadLetterReason.UNSUPPORTED_EVENT: "Handler does not support this event name/schema version",
    EventDeliveryDeadLetterReason.INVALID_DELIVERY: "Delivery referenced a business record that no longer exists",
}
RETRYABLE_ERRORS = [
    "Connection to security_audit sink timed out after 5s",
    "Downstream webhook returned 503 Service Unavailable",
    "Redis connection reset while marking delivery ENQUEUED",
    "SMTP relay refused connection: 421 too many concurrent connections",
]

# (event_name, schema_version, weight) — only events with a registered handler ever
# produce an Event Delivery, matching the monitor's own event-types filter.
WEIGHTED_EVENTS = [
    (ORGANIZATION_ROLE_CHANGED, 1, 3),
    (AGENT_ACCESS_GRANTED, 1, 3),
    (AGENT_ACCESS_REVOKED, 1, 2),
    (AGENT_GENERAL_ACCESS_CHANGED, 1, 2),
    (AGENT_STARTED, 1, 4),
    (AGENT_STOPPED, 1, 4),
]

# Final status distribution, weighted to look like a healthy-but-not-perfect pipeline.
STATUS_WEIGHTS = {
    "SUCCEEDED": 55,
    "PENDING": 12,
    "ENQUEUED": 8,
    "PROCESSING": 5,
    "DEAD_LETTERED": 20,
}


def _get_or_create_organizations(delegate: PostgresRepositoryDelegate) -> list[Organization]:
    with Session(delegate.engine) as session:
        existing = list(session.exec(select(Organization)))
    if len(existing) >= 3:
        return existing
    existing_names = {org.name for org in existing}
    created = list(existing)
    for name in ORG_NAMES:
        if name in existing_names:
            continue
        org = Organization(name=name, description=f"{name} — seeded for local Event Delivery Monitor testing")
        delegate.save(org)
        created.append(org)
    return created


def _payload_for(event_name: str, organization_id: UUID) -> dict:
    if event_name == ORGANIZATION_ROLE_CHANGED:
        previous_role, new_role = random.sample(ORGANIZATION_ROLES, 2)
        return {
            "organization_id": str(organization_id),
            "membership_id": str(uuid4()),
            "user_id": str(uuid4()),
            "previous_role": previous_role,
            "new_role": new_role,
        }
    if event_name == AGENT_ACCESS_GRANTED:
        return {
            "organization_id": str(organization_id),
            "agent_id": str(uuid4()),
            "membership_id": str(uuid4()),
            "access_role_id": str(uuid4()),
        }
    if event_name == AGENT_ACCESS_REVOKED:
        return {
            "organization_id": str(organization_id),
            "agent_id": str(uuid4()),
            "membership_id": str(uuid4()),
            "previous_access_role_id": str(uuid4()),
        }
    if event_name == AGENT_GENERAL_ACCESS_CHANGED:
        return {
            "organization_id": str(organization_id),
            "agent_id": str(uuid4()),
            "previous_access_role_id": str(uuid4()) if random.random() > 0.3 else None,
            "new_access_role_id": str(uuid4()),
        }
    if event_name in (AGENT_STARTED, AGENT_STOPPED):
        previous_status, new_status = ("STARTING", "RUNNING") if event_name == AGENT_STARTED else ("RUNNING", "STOPPED")
        return {
            "organization_id": str(organization_id),
            "agent_id": str(uuid4()),
            "agent_name": random.choice(AGENT_NAMES),
            "previous_status": previous_status,
            "new_status": new_status,
            "platform": random.choice(PLATFORMS),
            "runtime": random.choice(RUNTIMES),
        }
    raise ValueError(f"No fixture payload builder for {event_name}")


def _pick_weighted(weighted: list[tuple], rng: random.Random):
    items = [item for item, _weight in weighted]
    weights = [weight for _item, weight in weighted]
    return rng.choices(items, weights=weights, k=1)[0]


def _random_recent_datetime(rng: random.Random, *, max_days_ago: int = 30) -> datetime:
    seconds_ago = rng.uniform(0, max_days_ago * 86400)
    return datetime.now(UTC) - timedelta(seconds=seconds_ago)


def _set_created_at(delegate: PostgresRepositoryDelegate, delivery_id: UUID, created_at: datetime) -> None:
    with delegate.engine.begin() as connection:
        connection.execute(
            text("UPDATE event_delivery SET created_at = :created_at WHERE id = :id"),
            {"created_at": created_at, "id": delivery_id},
        )


def _null_enqueued_at(delegate: PostgresRepositoryDelegate, delivery_id: UUID) -> None:
    with delegate.engine.begin() as connection:
        connection.execute(
            text("UPDATE event_delivery SET enqueued_at = NULL WHERE id = :id"),
            {"id": delivery_id},
        )


def _null_claimed_at(delegate: PostgresRepositoryDelegate, delivery_id: UUID) -> None:
    with delegate.engine.begin() as connection:
        connection.execute(
            text("UPDATE event_delivery SET claimed_at = NULL WHERE id = :id"),
            {"id": delivery_id},
        )


def _backdate_enqueued_at(delegate: PostgresRepositoryDelegate, delivery_id: UUID, value: datetime) -> None:
    with delegate.engine.begin() as connection:
        connection.execute(
            text("UPDATE event_delivery SET enqueued_at = :value WHERE id = :id"),
            {"value": value, "id": delivery_id},
        )


def _backdate_claimed_at(delegate: PostgresRepositoryDelegate, delivery_id: UUID, value: datetime) -> None:
    with delegate.engine.begin() as connection:
        connection.execute(
            text("UPDATE event_delivery SET claimed_at = :value WHERE id = :id"),
            {"value": value, "id": delivery_id},
        )


def _advance_delivery(
    repository: OutboxMessageRepository,
    delivery: EventDelivery,
    *,
    delegate: PostgresRepositoryDelegate,
    target_status: str,
    rng: random.Random,
    unknown_age: bool,
) -> None:
    created_at = _random_recent_datetime(rng)
    _set_created_at(delegate, delivery.id, created_at)

    if target_status == "PENDING":
        if unknown_age:
            # Simulate an operational anomaly: PENDING with no fallback timestamp other
            # than created_at is normal, so unknown-age for PENDING isn't representable
            # the same way — instead backdate far enough to look clearly stale.
            _set_created_at(delegate, delivery.id, datetime.now(UTC) - timedelta(hours=rng.uniform(2, 48)))
        return

    enqueued_at = created_at + timedelta(seconds=rng.uniform(1, 30))
    repository.mark_delivery_enqueued(delivery.id, enqueued_at=enqueued_at)
    if target_status == "ENQUEUED":
        if unknown_age:
            _null_enqueued_at(delegate, delivery.id)
        elif rng.random() < 0.3:
            # Stale enqueued: push enqueued_at well past the reconciler's threshold.
            _backdate_enqueued_at(delegate, delivery.id, datetime.now(UTC) - timedelta(minutes=rng.uniform(10, 120)))
        return

    claimed_at = enqueued_at + timedelta(seconds=rng.uniform(1, 15))
    repository.claim_delivery(delivery.id, claimed_at=claimed_at)
    if target_status == "PROCESSING":
        if unknown_age:
            _null_claimed_at(delegate, delivery.id)
        elif rng.random() < 0.3:
            _backdate_claimed_at(delegate, delivery.id, datetime.now(UTC) - timedelta(minutes=rng.uniform(20, 180)))
        return

    completed_at = claimed_at + timedelta(seconds=rng.uniform(1, 20))
    if target_status == "SUCCEEDED":
        repository.mark_delivery_succeeded(delivery.id, completed_at=completed_at)
        return

    if target_status == "DEAD_LETTERED":
        reason = rng.choice(DEAD_LETTER_REASONS)
        # A realistic terminal delivery usually has a few prior retryable failures on
        # its way to exhaustion; simulate one so attempt_count looks plausible.
        if rng.random() < 0.6:
            repository.mark_delivery_retryable_failure(delivery.id, rng.choice(RETRYABLE_ERRORS))
            repository.claim_delivery(delivery.id, claimed_at=claimed_at + timedelta(minutes=1))
        repository.mark_delivery_dead_lettered(
            delivery.id,
            reason=reason,
            error=DEAD_LETTER_ERRORS[reason],
            completed_at=completed_at,
        )
        return

    raise ValueError(f"Unhandled target status {target_status}")


def seed(count: int, seed_value: int | None) -> None:
    rng = random.Random(seed_value)
    config = get_config()
    delegate = PostgresRepositoryDelegate(config)
    repository = OutboxMessageRepository(delegate=delegate)

    organizations = _get_or_create_organizations(delegate)
    print(f"Using {len(organizations)} Organization(s): {', '.join(org.name for org in organizations)}")

    status_names = list(STATUS_WEIGHTS.keys())
    status_weight_values = list(STATUS_WEIGHTS.values())

    created_count = 0
    for _ in range(count):
        organization = rng.choice(organizations)
        event_name, schema_version = _pick_weighted(
            [((name, version), weight) for name, version, weight in WEIGHTED_EVENTS], rng
        )
        payload = _payload_for(event_name, organization.id)

        event = EVENT_REGISTRY.build_event(
            event_name=event_name,
            schema_version=schema_version,
            occurred_at=datetime.now(UTC),
            organization_id=organization.id,
            actor=ActorIdentity(type=ActorIdentityType.USER, id=uuid4(), organization_id=organization.id),
            subject=SubjectIdentity(type=SubjectIdentityType.AGENT, id=uuid4(), organization_id=organization.id),
            correlation_id=uuid4(),
            payload=payload,
        )
        repository.create(event, EVENT_REGISTRY)
        deliveries = repository.list_deliveries_for_event(event.event_id)

        target_status = rng.choices(status_names, weights=status_weight_values, k=1)[0]
        for delivery in deliveries:
            unknown_age = target_status != "SUCCEEDED" and rng.random() < 0.04
            _advance_delivery(
                repository,
                delivery,
                delegate=delegate,
                target_status=target_status,
                rng=rng,
                unknown_age=unknown_age,
            )
            created_count += 1

    print(f"Seeded {created_count} Event Deliveries across {count} Domain Events.")
    delegate.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=200, help="Number of Domain Events to emit (default: 200)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible output")
    args = parser.parse_args()
    seed(args.count, args.seed)


if __name__ == "__main__":
    main()
