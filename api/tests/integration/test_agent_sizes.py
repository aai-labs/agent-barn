"""Integration tests for the Agent Size catalog (Agent Sizes, PR 1).

Platform Administrators keep the catalog; every Agent starts on its default size, which the
migration seeds as "Standard" with the values Agents always ran with. No Organization can
read or change it yet.
"""

from uuid import uuid4, uuid7

import pytest
from fastapi import status
from hamcrest import assert_that, contains_exactly, contains_inanyorder, equal_to, has_entries, has_length

from api.domains.agent_sizes.models import STANDARD_SIZE_ID
from api.domains.events.catalog import (
    PLATFORM_AGENT_SIZE_CHANGED,
    PLATFORM_AGENT_SIZE_CREATED,
    PLATFORM_AGENT_SIZE_DELETED,
)
from api.domains.events.models import EventScope, OutboxMessage
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_URL = "/api/v1/platform/agent-sizes"
_MIB = 1024**2
_GIB = 1024**3

_BASE_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "API_EXTERNAL_URL": "https://api.test.com",
            "SKIP_SLACK_TOKEN_VALIDATION": "true",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
]

_LARGE = {
    "name": "Large",
    "cpu_request_millicores": 500,
    "cpu_limit_millicores": 2000,
    "memory_request_bytes": 2 * _GIB,
    "memory_limit_bytes": 4 * _GIB,
}


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


def _create(context, body: dict | None = None):
    return context.client.post(_URL, json=body or _LARGE, headers=_auth(context.access_token))


def _patch(context, size_id, body: dict):
    return context.client.patch(f"{_URL}/{size_id}", json=body, headers=_auth(context.access_token))


def _events(context, name: str) -> list[OutboxMessage]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [message for message in messages if message.event_name == name]


def _sizes(context) -> list[dict]:
    return context.client.get(_URL, headers=_auth(context.access_token)).json()


# --- authorization -------------------------------------------------------


def test_the_catalog_requires_authentication():
    with given(_BASE_GIVEN) as context:
        assert_that(context.client.get(_URL).status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_an_organization_owner_can_neither_read_nor_change_the_catalog():
    with given([*_BASE_GIVEN, there_is_an_organization_with_user_and_access_token(email="size-owner@example.com")]) as (
        context
    ):
        headers = _auth(context.access_token)

        assert_that(context.client.get(_URL, headers=headers).status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(
            context.client.post(_URL, json=_LARGE, headers=headers).status_code, equal_to(status.HTTP_403_FORBIDDEN)
        )
        assert_that(
            context.client.patch(f"{_URL}/{STANDARD_SIZE_ID}", json={"name": "x"}, headers=headers).status_code,
            equal_to(status.HTTP_403_FORBIDDEN),
        )
        assert_that(
            context.client.delete(f"{_URL}/{STANDARD_SIZE_ID}", headers=headers).status_code,
            equal_to(status.HTTP_403_FORBIDDEN),
        )


def test_a_read_only_api_key_can_read_the_catalog_but_not_change_it():
    with given([*_BASE_GIVEN, *_platform_admin("size-admin-key@example.com")]) as context:
        response = context.client.post(
            "/api/v1/auth/me/api-keys",
            json={"name": "Automation", "access_mode": "READ_ONLY"},
            headers=_auth(context.access_token),
        )
        key = _auth(response.json()["token"])

        assert_that(context.client.get(_URL, headers=key).status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            context.client.post(_URL, json=_LARGE, headers=key).status_code, equal_to(status.HTTP_403_FORBIDDEN)
        )
        assert_that(_sizes(context), has_length(1))


# --- the catalog ---------------------------------------------------------


def test_the_catalog_starts_with_standard_as_the_default():
    with given([*_BASE_GIVEN, *_platform_admin("size-admin-list@example.com")]) as context:
        [standard] = _sizes(context)

        assert_that(
            standard,
            has_entries(
                id=str(STANDARD_SIZE_ID),
                name="Standard",
                cpu_request_millicores=50,
                cpu_limit_millicores=500,
                memory_request_bytes=320 * _MIB,
                memory_limit_bytes=1 * _GIB,
                enabled=True,
                is_default=True,
            ),
        )


def test_a_created_size_is_listed_and_audited_with_its_values():
    with given([*_BASE_GIVEN, *_platform_admin("size-admin-create@example.com")]) as context:
        with when("the admin adds a size"):
            response = _create(context, {**_LARGE, "name": "  Large  "})

        with then("it is saved, trimmed, not the default, and recorded once"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            created = response.json()
            assert_that(created, has_entries(name="Large", enabled=True, is_default=False))
            assert_that([size["name"] for size in _sizes(context)], contains_inanyorder("Standard", "Large"))
            [event] = _events(context, PLATFORM_AGENT_SIZE_CREATED)
            assert_that(event.event_scope, equal_to(EventScope.PLATFORM))
            assert_that(
                event.payload,
                has_entries(subject_display="Large", memory_limit_bytes=4 * _GIB, is_default=False),
            )


def test_a_name_is_unique_whatever_its_case():
    with given([*_BASE_GIVEN, *_platform_admin("size-admin-unique@example.com")]) as context:
        response = _create(context, {**_LARGE, "name": "STANDARD"})

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(_events(context, PLATFORM_AGENT_SIZE_CREATED), has_length(0))


@pytest.mark.parametrize(
    "override",
    [
        {"cpu_request_millicores": 3000},
        {"memory_request_bytes": 8 * _GIB},
        {"cpu_limit_millicores": 0},
        {"memory_limit_bytes": -1},
        {"cpu_limit_millicores": 64_001},
        {"memory_limit_bytes": 256 * _GIB + 1},
        {"storage_bytes": 512 * _MIB},
        {"storage_bytes": 100 * _GIB + 1},
        {"name": "   "},
        {"is_default": True},
    ],
)
def test_a_size_that_cannot_run_is_refused(override):
    with given([*_BASE_GIVEN, *_platform_admin("size-admin-invalid@example.com")]) as context:
        response = _create(context, {**_LARGE, **override})

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
        assert_that(_sizes(context), has_length(1))


def test_an_edit_is_checked_against_the_values_it_keeps():
    with given([*_BASE_GIVEN, *_platform_admin("size-admin-merge@example.com")]) as context:
        large = _create(context).json()

        with when("only the request is raised, above the stored limit"):
            response = _patch(context, large["id"], {"memory_request_bytes": 5 * _GIB})

        with then("it is refused, and nothing is recorded"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
            assert_that(_events(context, PLATFORM_AGENT_SIZE_CHANGED), has_length(0))


def test_each_changed_field_leaves_one_event_and_an_unchanged_save_none():
    with given([*_BASE_GIVEN, *_platform_admin("size-admin-edit@example.com")]) as context:
        large = _create(context).json()

        _patch(context, large["id"], {"name": "Large", "cpu_limit_millicores": 2000})
        assert_that(_events(context, PLATFORM_AGENT_SIZE_CHANGED), has_length(0))

        response = _patch(context, large["id"], {"memory_limit_bytes": 6 * _GIB, "sort_order": 3})

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json(), has_entries(memory_limit_bytes=6 * _GIB, sort_order=3))
        moves = [
            (e.payload["setting"], e.payload["previous"], e.payload["current"])
            for e in _events(context, PLATFORM_AGENT_SIZE_CHANGED)
        ]
        assert_that(
            moves,
            contains_inanyorder(("memory_limit_bytes", 4 * _GIB, 6 * _GIB), ("sort_order", 0, 3)),
        )


def test_a_null_or_false_default_is_refused():
    with given([*_BASE_GIVEN, *_platform_admin("size-admin-null@example.com")]) as context:
        assert_that(
            _patch(context, STANDARD_SIZE_ID, {"name": None}).status_code,
            equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT),
        )
        assert_that(
            _patch(context, STANDARD_SIZE_ID, {"is_default": False}).status_code,
            equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT),
        )


# --- the default ---------------------------------------------------------


def test_making_a_size_the_default_moves_it_atomically_and_records_both_sides():
    with given([*_BASE_GIVEN, *_platform_admin("size-admin-default@example.com")]) as context:
        large = _create(context).json()

        with when("the admin makes Large the default"):
            response = _patch(context, large["id"], {"is_default": True})

        with then("Large is the only default, and both changes are recorded together"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            defaults = [size["name"] for size in _sizes(context) if size["is_default"]]
            assert_that(defaults, contains_exactly("Large"))
            events = _events(context, PLATFORM_AGENT_SIZE_CHANGED)
            moves = [(e.payload["subject_display"], e.payload["setting"], e.payload["current"]) for e in events]
            assert_that(moves, contains_inanyorder(("Standard", "is_default", False), ("Large", "is_default", True)))
            assert_that({e.correlation_id for e in events}, has_length(1))


def test_the_default_can_be_neither_disabled_nor_deleted():
    with given([*_BASE_GIVEN, *_platform_admin("size-admin-guard@example.com")]) as context:
        headers = _auth(context.access_token)

        assert_that(
            _patch(context, STANDARD_SIZE_ID, {"enabled": False}).status_code, equal_to(status.HTTP_409_CONFLICT)
        )
        assert_that(
            context.client.delete(f"{_URL}/{STANDARD_SIZE_ID}", headers=headers).status_code,
            equal_to(status.HTTP_409_CONFLICT),
        )
        assert_that(_sizes(context)[0], has_entries(enabled=True, is_default=True))


def test_a_disabled_size_must_be_enabled_before_it_becomes_the_default():
    with given([*_BASE_GIVEN, *_platform_admin("size-admin-disabled@example.com")]) as context:
        large = _create(context, {**_LARGE, "enabled": False}).json()

        assert_that(_patch(context, large["id"], {"is_default": True}).status_code, equal_to(status.HTTP_409_CONFLICT))

        response = _patch(context, large["id"], {"enabled": True, "is_default": True})
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json(), has_entries(enabled=True, is_default=True))


def test_a_size_that_is_not_the_default_can_be_deleted_and_the_deletion_is_audited():
    with given([*_BASE_GIVEN, *_platform_admin("size-admin-delete@example.com")]) as context:
        large = _create(context).json()
        headers = _auth(context.access_token)

        assert_that(
            context.client.delete(f"{_URL}/{large['id']}", headers=headers).status_code,
            equal_to(status.HTTP_204_NO_CONTENT),
        )
        assert_that([size["name"] for size in _sizes(context)], contains_exactly("Standard"))
        [event] = _events(context, PLATFORM_AGENT_SIZE_DELETED)
        assert_that(event.payload, has_entries(subject_display="Large", memory_request_bytes=2 * _GIB))
        assert_that(
            context.client.delete(f"{_URL}/{uuid4()}", headers=headers).status_code,
            equal_to(status.HTTP_404_NOT_FOUND),
        )
        assert_that(_patch(context, uuid4(), {"name": "x"}).status_code, equal_to(status.HTTP_404_NOT_FOUND))


# --- what Agents start on ------------------------------------------------


def _started_resources(context):
    deployment = context.injector.get(KubernetesClient).create_deployment.call_args.args[1]
    pod = deployment.spec.template.spec
    return pod.containers[0].resources, pod.init_containers[0].resources


def test_an_agent_starts_on_the_default_size_and_picks_up_a_new_default_at_its_next_start():
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="size-agent-owner@example.com"),
            use_org_for_auth(),
            there_is_a_template(),
            there_is_an_agent(),
        ]
    ) as context:
        owner_token, agent_id = context.access_token, context.agent.id
        start = f"/api/v1/organizations/{{organization_id}}/agents/{agent_id}/start"
        stop = f"/api/v1/organizations/{{organization_id}}/agents/{agent_id}/stop"

        with when("the Agent starts with the catalog as seeded"):
            assert_that(
                context.client.post(start, headers=_auth(owner_token)).status_code, equal_to(status.HTTP_200_OK)
            )

        with then("its pod has exactly the resources Agents always had"):
            agent, init = _started_resources(context)
            assert_that(agent.requests, equal_to({"memory": "320Mi", "cpu": "50m"}))
            assert_that(agent.limits, equal_to({"memory": "1Gi", "cpu": "500m"}))
            assert_that(init, equal_to(agent))

        with when("a Platform Administrator makes a larger size the default, and the Agent restarts"):
            for step in _platform_admin("size-agent-admin@example.com"):
                step(context)
            large = _create(context).json()
            _patch(context, large["id"], {"is_default": True})
            context.client.post(stop, headers=_auth(owner_token))
            assert_that(
                context.client.post(start, headers=_auth(owner_token)).status_code, equal_to(status.HTTP_200_OK)
            )

        with then("the agent container runs on it, and the init container keeps its fixed block"):
            agent, init = _started_resources(context)
            assert_that(agent.requests, equal_to({"memory": "2Gi", "cpu": "500m"}))
            assert_that(agent.limits, equal_to({"memory": "4Gi", "cpu": "2000m"}))
            assert_that(init.requests, equal_to({"memory": "320Mi", "cpu": "50m"}))
