"""Integration tests for the storage an Agent Size gives an Agent's volume.

A size says how large the Agent's volume (PVC) is: a new volume is created at that size, an
existing one grows to it at the Agent's next start, and none is ever shrunk. Standard keeps the
1Gi every Agent always had.
"""

from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, equal_to, has_entries
from kubernetes.client.exceptions import ApiException

from api.domains.agent_sizes.models import GIB, STANDARD_SIZE_ID
from api.domains.agents.builders.common import build_pvc
from api.domains.agents.models import Agent
from api.domains.events.catalog import PLATFORM_AGENT_SIZE_CHANGED, PLATFORM_AGENT_SIZE_CREATED
from api.domains.events.models import OutboxMessage
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

_SIZES = "/api/v1/platform/agent-sizes"
_AGENTS = "/api/v1/organizations/{organization_id}/agents"

_GIVEN = [
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
    there_is_an_organization_with_user_and_access_token(email="storage-owner@example.com"),
    use_org_for_auth(),
    there_is_a_template(),
]

_BIG = {
    "name": "Big disk",
    "cpu_request_millicores": 50,
    "cpu_limit_millicores": 500,
    "memory_request_bytes": 320 * 1024**2,
    "memory_limit_bytes": 1 * GIB,
    "storage_bytes": 10 * GIB,
}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _platform_admin(context) -> str:
    saved = {
        name: getattr(context, name, None) for name in ("user", "organization", "organization_user", "access_token")
    }
    context.organization = None
    admin_id = uuid7()
    there_is_a_user(id=admin_id, email=f"platform-{admin_id}@example.com", is_platform_admin=True)(context)
    there_is_an_access_token_for_user(admin_id)(context)
    token = context.access_token
    for name, value in saved.items():
        setattr(context, name, value)
    return token


def _make_default(context, admin: str, body: dict) -> dict:
    size = context.client.post(_SIZES, json=body, headers=_auth(admin)).json()
    context.client.patch(f"{_SIZES}/{size['id']}", json={"is_default": True}, headers=_auth(admin))
    return size


def _start(context):
    return context.client.post(f"{_AGENTS}/{context.agent.id}/start", headers=_auth(context.access_token))


def _stop(context):
    return context.client.post(f"{_AGENTS}/{context.agent.id}/stop", headers=_auth(context.access_token))


def _requested_storage(context) -> str:
    manifest = context.injector.get(KubernetesClient).create_pvc.call_args.args[1]
    return manifest.spec.resources.requests["storage"]


def _stored_agent(context) -> Agent:
    agent = context.injector.get(PostgresRepositoryDelegate).find_by_id(Agent, context.agent.id)
    assert agent is not None
    return agent


def _volume(context) -> int | None:
    """The volume size the Agent's last start recorded."""
    return (_stored_agent(context).running_resources or {}).get("storage_bytes")


def _events(context, name: str) -> list[OutboxMessage]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [message for message in messages if message.event_name == name]


# --- the catalog -------------------------------------------------------------------


def test_standard_has_the_1gi_volume_every_agent_always_had():
    with given(_GIVEN) as context:
        admin = _platform_admin(context)

        sizes = context.client.get(_SIZES, headers=_auth(admin)).json()

        assert_that(sizes[0], has_entries(id=str(STANDARD_SIZE_ID), storage_bytes=1 * GIB))


def test_a_size_keeps_its_storage_and_audits_it():
    with given(_GIVEN) as context:
        admin = _platform_admin(context)

        with when("a size is added with a 10Gi volume and then raised to 20Gi"):
            created = context.client.post(_SIZES, json=_BIG, headers=_auth(admin)).json()
            edited = context.client.patch(
                f"{_SIZES}/{created['id']}", json={"storage_bytes": 20 * GIB}, headers=_auth(admin)
            )

        with then("both are stored and recorded"):
            assert_that(created, has_entries(storage_bytes=10 * GIB))
            assert_that(edited.json(), has_entries(storage_bytes=20 * GIB))
            [added] = _events(context, PLATFORM_AGENT_SIZE_CREATED)
            assert_that(added.payload, has_entries(storage_bytes=10 * GIB))
            [changed] = _events(context, PLATFORM_AGENT_SIZE_CHANGED)
            assert_that(changed.payload, has_entries(setting="storage_bytes", previous=10 * GIB, current=20 * GIB))


def test_a_size_without_storage_gets_the_1gi_minimum():
    with given(_GIVEN) as context:
        admin = _platform_admin(context)
        body = {key: value for key, value in _BIG.items() if key != "storage_bytes"}

        created = context.client.post(_SIZES, json=body, headers=_auth(admin))

        assert_that(created.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(created.json(), has_entries(storage_bytes=1 * GIB))


# --- the volume --------------------------------------------------------------------


def test_a_new_agent_gets_a_standard_volume_exactly_as_before():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        assert_that(_start(context).status_code, equal_to(status.HTTP_200_OK))

        assert_that(_requested_storage(context), equal_to("1Gi"))
        assert_that(context.injector.get(KubernetesClient).patch_pvc_storage.called, equal_to(False))
        assert_that(_volume(context), equal_to(1 * GIB))


def test_a_new_volume_is_created_at_its_sizes_storage():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        _make_default(context, _platform_admin(context), _BIG)

        _start(context)

        assert_that(_requested_storage(context), equal_to("10Gi"))
        assert_that(_volume(context), equal_to(10 * GIB))


def test_an_existing_smaller_volume_grows_at_the_next_start():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        k8s = context.injector.get(KubernetesClient)
        _start(context)
        admin = _platform_admin(context)

        with when("its size gets a bigger volume while it runs"):
            _make_default(context, admin, _BIG)
            read = context.client.get(f"{_AGENTS}/{context.agent.id}", headers=_auth(context.access_token)).json()

        with then("a restart is pending"):
            assert_that(read["pending_size"], equal_to(True))

        with when("it restarts, finding its 1Gi volume already there"):
            k8s.create_pvc.side_effect = None
            k8s.create_pvc.return_value = build_pvc(context.agent.id, context.organization.id, "ns")
            _stop(context)
            _start(context)

        with then("the volume is grown to 10Gi and nothing is pending"):
            k8s.patch_pvc_storage.assert_called_once()
            assert_that(k8s.patch_pvc_storage.call_args.args[2], equal_to("10Gi"))
            assert_that(_volume(context), equal_to(10 * GIB))
            read = context.client.get(f"{_AGENTS}/{context.agent.id}", headers=_auth(context.access_token)).json()
            assert_that(read["pending_size"], equal_to(False))


def test_a_volume_the_cluster_cannot_grow_still_starts_and_stays_pending():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        k8s = context.injector.get(KubernetesClient)
        _make_default(context, _platform_admin(context), _BIG)
        k8s.create_pvc.side_effect = None
        k8s.create_pvc.return_value = build_pvc(context.agent.id, context.organization.id, "ns")
        k8s.patch_pvc_storage.side_effect = ApiException(status=403, reason="Forbidden")

        response = _start(context)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["pending_size"], equal_to(True))
        assert_that(_volume(context), equal_to(1 * GIB))


def test_a_volume_is_never_shrunk():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        k8s = context.injector.get(KubernetesClient)
        k8s.create_pvc.side_effect = None
        k8s.create_pvc.return_value = build_pvc(context.agent.id, context.organization.id, "ns", storage_bytes=20 * GIB)

        response = _start(context)

        assert_that(k8s.patch_pvc_storage.called, equal_to(False))
        assert_that(response.json()["pending_size"], equal_to(False))
        assert_that(_volume(context), equal_to(20 * GIB))
