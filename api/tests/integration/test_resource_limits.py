"""Integration tests for the platform capacity limits (AF-170).

A Platform Administrator enters the ceilings the namespace's ResourceQuota sets, because
the tenant service account cannot read the quota. Each change leaves one audit Event, and a
save that changes nothing leaves none.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from uuid import uuid7

import pytest
from fastapi import status
from hamcrest import assert_that, contains_inanyorder, empty, equal_to, has_length, is_not, none
from pydantic import ValidationError

from api.domains.events.catalog import PLATFORM_RESOURCE_LIMITS_CHANGED
from api.domains.events.models import EventScope, OutboxMessage
from api.domains.resource_limits.models import (
    PLATFORM_RESOURCE_LIMITS_ID,
    PlatformResourceLimits,
    ResourceLimitsUpdate,
)
from api.domains.resource_limits.repository import ResourceLimitsRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.resource_usage import MockPrometheusModule
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_URL = "/api/v1/platform/resource-limits"
_GiB = 1024**3

_BASE_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "SKIP_SLACK_TOKEN_VALIDATION": "true",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), MockPrometheusModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _platform_admin(email: str):
    """A Platform Administrator with no Membership, whose token lands last in context."""
    admin_id = uuid7()

    def step(context):
        original_organization = getattr(context, "organization", None)
        context.organization = None
        there_is_a_user(id=admin_id, email=email, is_platform_admin=True)(context)
        context.organization = original_organization
        there_is_an_access_token_for_user(user_id=admin_id)(context)

    return [step]


def _put(context, body: dict | None = None, *, raw: str | None = None):
    headers = _auth(context.access_token)
    if raw is not None:
        return context.client.put(_URL, content=raw, headers={**headers, "content-type": "application/json"})
    return context.client.put(_URL, json=body or {}, headers=headers)


def _limit_events(context) -> list[OutboxMessage]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [m for m in messages if m.event_name == PLATFORM_RESOURCE_LIMITS_CHANGED]


# --- authorization -------------------------------------------------------


def test_setting_limits_requires_authentication():
    with given(_BASE_GIVEN) as context:
        response = context.client.put(_URL, json={"limits_memory_bytes": 70 * _GiB})

        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_an_organization_owner_cannot_set_the_platform_limits():
    with given(
        [*_BASE_GIVEN, there_is_an_organization_with_user_and_access_token(email="owner-limits@example.com")]
    ) as context:
        with when("an owner without Platform Privilege tries to set a limit"):
            response = _put(context, {"limits_memory_bytes": 70 * _GiB})

        with then("it is refused and nothing is recorded"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(_limit_events(context), empty())


# --- saving ----------------------------------------------------------------


def test_the_first_save_creates_the_limits_and_returns_them():
    with given([*_BASE_GIVEN, *_platform_admin("admin-first@example.com")]) as context:
        with when("the admin enters both limits"):
            response = _put(context, {"limits_memory_bytes": 70 * _GiB, "limits_cpu_cores": 24.5})

        with then("they come back with a timestamp"):
            body = response.json()
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(body["limits_memory_bytes"], equal_to(70 * _GiB))
            assert_that(body["limits_cpu_cores"], equal_to(24.5))
            assert_that(body["updated_at"], is_not(none()))


def test_omitting_a_limit_leaves_it_and_null_clears_it():
    with given([*_BASE_GIVEN, *_platform_admin("admin-partial@example.com")]) as context:
        _put(context, {"limits_memory_bytes": 70 * _GiB, "limits_cpu_cores": 24})

        with when("only the CPU limit is sent"):
            changed = _put(context, {"limits_cpu_cores": 32}).json()

        with then("the memory limit is untouched"):
            assert_that(changed["limits_memory_bytes"], equal_to(70 * _GiB))
            assert_that(changed["limits_cpu_cores"], equal_to(32))

        with when("the memory limit is explicitly cleared"):
            cleared = _put(context, {"limits_memory_bytes": None}).json()

        with then("it is gone and the CPU limit stays"):
            assert_that(cleared["limits_memory_bytes"], none())
            assert_that(cleared["limits_cpu_cores"], equal_to(32))


def test_the_requests_ceilings_are_saved_and_returned_beside_the_limits():
    with given([*_BASE_GIVEN, *_platform_admin("admin-requests@example.com")]) as context:
        with when("the admin enters all four quota lines"):
            response = _put(
                context,
                {
                    "limits_memory_bytes": 52 * _GiB,
                    "limits_cpu_cores": 30,
                    "requests_memory_bytes": 20 * _GiB,
                    "requests_cpu_cores": 5,
                },
            )

        with then("each comes back under the quota's own name"):
            body = response.json()
            assert_that(body["limits_memory_bytes"], equal_to(52 * _GiB))
            assert_that(body["limits_cpu_cores"], equal_to(30))
            assert_that(body["requests_memory_bytes"], equal_to(20 * _GiB))
            assert_that(body["requests_cpu_cores"], equal_to(5))


def test_an_empty_save_changes_nothing_and_records_nothing():
    with given([*_BASE_GIVEN, *_platform_admin("admin-empty@example.com")]) as context:
        response = _put(context, {})

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["limits_memory_bytes"], none())
        assert_that(_limit_events(context), empty())


# --- validation ------------------------------------------------------------


def test_a_limit_that_cannot_be_real_is_refused():
    with given([*_BASE_GIVEN, *_platform_admin("admin-invalid@example.com")]) as context:
        bad_bodies = [
            {"limits_memory_bytes": 0},
            {"limits_memory_bytes": -1},
            {"limits_memory_bytes": 2**50 + 1},
            {"limits_cpu_cores": 0},
            {"limits_cpu_cores": -2},
            {"limits_cpu_cores": 100_001},
            {"requests_memory_bytes": 0},
            {"requests_memory_bytes": 2**50 + 1},
            {"requests_cpu_cores": 0},
            {"requests_cpu_cores": -1},
            # Not a limit at all: a setting that does not exist.
            {"pod_limit": 110},
        ]

        statuses = [_put(context, body).status_code for body in bad_bodies]

        assert_that(statuses, equal_to([status.HTTP_422_UNPROCESSABLE_ENTITY] * len(bad_bodies)))
        assert_that(_limit_events(context), empty())


def test_a_limit_that_is_not_a_number_is_refused():
    with given([*_BASE_GIVEN, *_platform_admin("admin-text@example.com")]) as context:
        response = _put(context, raw='{"limits_memory_bytes": "lots"}')

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_the_update_model_rejects_nan_and_infinity():
    # At the model, not over HTTP: FastAPI cannot write its own 422 body for a NaN input,
    # so a request carrying one fails before this model's verdict reaches the caller. The
    # UI never sends one, since it sends numbers it parsed from a text box.
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            ResourceLimitsUpdate(limits_cpu_cores=value)
        with pytest.raises(ValidationError):
            ResourceLimitsUpdate(requests_cpu_cores=value)


# --- the audit trail -------------------------------------------------------


def test_each_changed_limit_leaves_one_platform_event_with_its_before_and_after():
    with given([*_BASE_GIVEN, *_platform_admin("admin-audit@example.com")]) as context:
        with when("the admin sets memory, then raises it and sets CPU in one save"):
            _put(context, {"limits_memory_bytes": 50 * _GiB})
            _put(context, {"limits_memory_bytes": 70 * _GiB, "limits_cpu_cores": 24})

        with then("three events exist: one per limit that moved"):
            events = _limit_events(context)
            assert_that(events, has_length(3))
            moves = [(e.payload["setting"], e.payload["previous"], e.payload["current"]) for e in events]
            assert_that(
                moves,
                contains_inanyorder(
                    ("limits_memory_bytes", None, float(50 * _GiB)),
                    ("limits_memory_bytes", float(50 * _GiB), float(70 * _GiB)),
                    ("limits_cpu_cores", None, 24.0),
                ),
            )

        with then("they are Platform events about the limits, not about any Organization"):
            for event in events:
                assert_that(event.event_scope, equal_to(EventScope.PLATFORM))
                assert_that(event.organization_id, none())
                assert_that(event.subject["type"], equal_to("SYSTEM"))
                assert_that(event.subject["id"], equal_to(str(PLATFORM_RESOURCE_LIMITS_ID)))
                assert_that(event.payload["actor_display"], is_not(empty()))


def test_a_changed_requests_ceiling_leaves_its_own_event_named_as_the_quota_names_it():
    with given([*_BASE_GIVEN, *_platform_admin("admin-audit-requests@example.com")]) as context:
        _put(context, {"requests_memory_bytes": 20 * _GiB, "requests_cpu_cores": 5})

        moves = [(e.payload["setting"], e.payload["previous"], e.payload["current"]) for e in _limit_events(context)]
        assert_that(
            moves,
            contains_inanyorder(
                ("requests_memory_bytes", None, float(20 * _GiB)),
                ("requests_cpu_cores", None, 5.0),
            ),
        )


def test_saving_the_same_values_again_records_nothing():
    with given([*_BASE_GIVEN, *_platform_admin("admin-same@example.com")]) as context:
        _put(context, {"limits_memory_bytes": 70 * _GiB, "limits_cpu_cores": 24})
        before = len(_limit_events(context))

        with when("the admin saves the same limits again"):
            response = _put(context, {"limits_memory_bytes": 70 * _GiB, "limits_cpu_cores": 24})

        with then("no Event is staged: an audit trail of unchanged values is noise"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_limit_events(context), has_length(before))


def test_clearing_a_limit_is_recorded_as_a_change_to_none():
    with given([*_BASE_GIVEN, *_platform_admin("admin-clear@example.com")]) as context:
        _put(context, {"limits_cpu_cores": 24})

        _put(context, {"limits_cpu_cores": None})

        last = max(_limit_events(context), key=lambda e: e.occurred_at)
        assert_that(last.payload["setting"], equal_to("limits_cpu_cores"))
        assert_that(last.payload["previous"], equal_to(24.0))
        assert_that(last.payload["current"], none())


# --- the very first save ---------------------------------------------------


def _save_when_released(repository: ResourceLimitsRepository, barrier: threading.Barrier, gib: int):
    barrier.wait()  # both are past their setup and about to write
    return repository.set_with_events(
        {"limits_memory_bytes": gib * _GiB}, actor_user_id=uuid7(), actor_display=f"admin-{gib}"
    )


def test_two_administrators_saving_for_the_first_time_at_once_both_succeed():
    """With no row yet, FOR UPDATE has nothing to lock, so both used to INSERT it and one failed."""
    with given(_BASE_GIVEN) as context:
        repository = context.injector.get(ResourceLimitsRepository)
        delegate = context.injector.get(PostgresRepositoryDelegate)
        seen: set = set()

        for _ in range(8):
            # Back to "no row yet", which is the only state the race exists in.
            delegate.delete_all(PlatformResourceLimits)
            barrier = threading.Barrier(2)

            with ThreadPoolExecutor(max_workers=2) as pool:
                # map re-raises whatever either thread raised, so an IntegrityError fails here.
                results = list(pool.map(partial(_save_when_released, repository, barrier), (50, 70)))

            assert_that(results, has_length(2))
            events = [m for m in _limit_events(context) if m.event_id not in seen]
            seen.update(m.event_id for m in events)
            moves = [(m.payload["previous"], m.payload["current"]) for m in events]
            # One saved first (from nothing) and the other saved over it, and neither
            # recorded the same "previous" value as the other.
            assert_that(moves, has_length(2))
            first = next(move for move in moves if move[0] is None)
            second = next(move for move in moves if move[0] is not None)
            assert_that(second[0], equal_to(first[1]))
            stored = repository.get()
            assert stored is not None
            assert_that(float(stored.limits_memory_bytes or 0), equal_to(second[1]))


def test_a_first_save_that_changes_nothing_leaves_no_row_and_reports_none():
    with given([*_BASE_GIVEN, *_platform_admin("admin-first-noop@example.com")]) as context:
        with when("the admin saves a blank limit when none was ever set"):
            response = _put(context, {"limits_memory_bytes": None})

        with then("nothing is stored, and the answer says so rather than inventing a time"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["updated_at"], none())
            assert_that(response.json()["limits_memory_bytes"], none())
            assert_that(context.injector.get(ResourceLimitsRepository).get(), none())
            assert_that(_limit_events(context), empty())
