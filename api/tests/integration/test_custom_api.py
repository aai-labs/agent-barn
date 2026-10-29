import hashlib
import json
import tomllib
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_length, is_, none, not_

from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.custom_api.repository import CustomApiRepository
from api.domains.custom_api.runtime import connection_snapshot, materialize_custom_api
from api.domains.events.catalog import AGENT_UPDATED
from api.domains.events.models import OutboxMessage
from api.domains.integrations.repository import IntegrationRepository
from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID, AGENT_OWNER_ROLE_ID, AGENT_VIEWER_ROLE_ID
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_agent_access,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(status=AgentStatus.STOPPED),
]


def _path(context, suffix=""):
    return f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/custom-api-connections{suffix}"


def _headers(context):
    return {"Authorization": f"Bearer {context.access_token}"}


def _create(context, slug="inventory", isolated=False):
    return context.client.post(
        _path(context),
        headers=_headers(context),
        json={
            "name": slug.replace("-", " ").title(),
            "base_url": "https://api.example.com/v1",
            "isolated": isolated,
            "auth": {"type": "bearer", "token": "fixture-private-token"},
            "headers": [
                {"name": "X-Tenant-Key", "value": "fixture-secret-header", "secret": True},
                {"name": "X-Api-Version", "value": "2026", "secret": False},
            ],
        },
    )


def test_crud_keeps_credentials_write_only_and_multiple_connections_independent():
    with given(_GIVEN) as context:
        with when("two named APIs are configured"):
            first = _create(context)
            second = _create(context, "billing", isolated=True)
        with then("both names exist and credentials never appear in read responses"):
            assert_that(first.status_code, equal_to(201))
            assert_that(second.status_code, equal_to(201))
            response = context.client.get(_path(context), headers=_headers(context))
            assert_that(response.json(), has_length(2))
            assert_that(response.text, not_(contains_string("fixture-private-token")))
            assert_that(response.text, not_(contains_string("fixture-secret-header")))
            assert_that(first.json()["isolated"], is_(False))
            assert_that(second.json()["isolated"], is_(True))
        with when("the name is updated without resubmitting secrets"):
            response = context.client.patch(
                _path(context, "/" + first.json()["id"]), headers=_headers(context), json={"name": "New inventory"}
            )
        with then("the credential remains usable and the other connection stays intact"):
            assert_that(response.status_code, equal_to(200))
            rows = context.injector.get(CustomApiRepository).runtime_connections(context.agent.id)
            artifacts = materialize_custom_api(
                rows, TEST_ENCRYPTION_KEY, "http://gateway.test", context.injector.get(CustomApiRepository)
            )
            configs = tomllib.loads(artifacts.files["custom-api-profiles.toml"])["profiles"]
            assert_that(configs["custom-api-inventory"]["auth_type"], equal_to("bearer_token"))
            assert_that("fixture-private-token" in artifacts.env.values(), is_(True))
            assert_that(configs["custom-api-billing"]["auth_type"], equal_to("none"))
            assert_that(json.dumps(configs), not_(contains_string("fixture-private-token")))
        with when("one connection is deleted"):
            response = context.client.delete(_path(context, "/" + first.json()["id"]), headers=_headers(context))
        with then("only the chosen connection disappears"):
            assert_that(response.status_code, equal_to(204))
            assert_that(context.client.get(_path(context), headers=_headers(context)).json(), has_length(1))


def test_duplicate_slug_and_ambiguous_auth_fail_without_echoing_secrets():
    with given(_GIVEN) as context:
        assert_that(_create(context).status_code, equal_to(201))
        assert_that(_create(context).status_code, equal_to(409))
        response = context.client.patch(
            _path(context, "/" + context.client.get(_path(context), headers=_headers(context)).json()[0]["id"]),
            headers=_headers(context),
            json={"auth": {"type": "basic", "username": "user"}},
        )
        assert_that(response.status_code, equal_to(422))
        assert_that(response.text, not_(contains_string("fixture-private-token")))


def test_identifier_is_derived_from_name_and_retained_after_rename():
    with given(_GIVEN) as context:
        created = context.client.post(
            _path(context),
            headers=_headers(context),
            json={"name": "Agent Barn Production", "base_url": "https://api.example.com/v1"},
        )
        assert_that(created.status_code, equal_to(201))
        assert_that(created.json()["slug"], equal_to("agent-barn-production"))
        updated = context.client.patch(
            _path(context, "/" + created.json()["id"]),
            headers=_headers(context),
            json={"name": "Reporting API"},
        )
        assert_that(updated.status_code, equal_to(200))
        assert_that(updated.json()["slug"], equal_to("agent-barn-production"))
        manual = context.client.post(
            _path(context),
            headers=_headers(context),
            json={"name": "Other API", "slug": "manually-set", "base_url": "https://api.example.com/v1"},
        )
        assert_that(manual.status_code, equal_to(422))


def test_wrong_agent_and_unauthenticated_requests_are_concealed():
    with given(_GIVEN) as context:
        row = _create(context).json()
        response = context.client.patch(
            _path(context, "/" + row["id"]).replace(str(context.agent.id), str(uuid4())),
            headers=_headers(context),
            json={"name": "stolen"},
        )
        assert_that(response.status_code, equal_to(404))
        assert_that(context.client.get(_path(context)).status_code, equal_to(401))


def test_gateway_tokens_are_connection_and_generation_bound_and_revoked_on_stop():
    with given(_GIVEN) as context:
        assert_that(_create(context, isolated=True).status_code, equal_to(201))
        repository = context.injector.get(CustomApiRepository)
        integrations = context.injector.get(IntegrationRepository)
        rows = repository.runtime_connections(context.agent.id)
        generation = integrations.begin(context.agent.id, connection_snapshot(rows))
        artifacts = materialize_custom_api(
            rows, TEST_ENCRYPTION_KEY, "http://gateway.test", repository, generation.generation
        )
        token = next(value for name, value in artifacts.env.items() if name.endswith("_GATEWAY"))
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        context.agent.status = AgentStatus.RUNNING
        context.injector.get(AgentRepository).save(context.agent)
        assert_that(repository.authorize_token(token_hash).id, equal_to(UUID(_create_id(rows))))
        integrations.set_state(context.agent.id, "stopping")
        assert_that(repository.authorize_token(token_hash).id, equal_to(rows[0].id))
        integrations.set_state(context.agent.id, "failed")
        assert_that(repository.authorize_token(token_hash), none())
        integrations.set_state(context.agent.id, "stopped")
        assert_that(repository.authorize_token(token_hash), none())
        integrations.begin(context.agent.id, connection_snapshot(rows))
        assert_that(repository.authorize_token(token_hash), none())


def _create_id(rows):
    return str(rows[0].id)


def test_listing_reconciles_a_ready_generation_as_applied():
    with given(_GIVEN) as context:
        assert_that(_create(context).status_code, equal_to(201))
        repository = context.injector.get(CustomApiRepository)
        integrations = context.injector.get(IntegrationRepository)
        rows = repository.runtime_connections(context.agent.id)
        generation = integrations.begin(context.agent.id, connection_snapshot(rows))
        materialize_custom_api(rows, TEST_ENCRYPTION_KEY, "http://gateway.test", repository, generation.generation)
        integrations.set_state(context.agent.id, "provisioned")
        context.agent.status = AgentStatus.RUNNING
        context.injector.get(AgentRepository).save(context.agent)

        response = context.client.get(_path(context), headers=_headers(context))

        assert_that(response.status_code, equal_to(200))
        assert_that(response.json()[0]["pending_apply"], equal_to(False))
        assert_that(integrations.runtime(context.agent.id).state, equal_to("ready"))


def test_connection_events_name_the_acting_user():
    with given(_GIVEN) as context:
        assert_that(_create(context).status_code, equal_to(201))

        messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)

        updated = [message for message in messages if message.event_name == AGENT_UPDATED]
        assert_that(updated, has_length(1))
        assert_that(updated[0].payload["actor_display"], equal_to("Test User"))


@pytest.mark.parametrize(
    "access_role,read_status,write_status",
    [
        (None, 404, 404),
        (AGENT_VIEWER_ROLE_ID, 200, 403),
        (AGENT_EDITOR_ROLE_ID, 200, 201),
        (AGENT_OWNER_ROLE_ID, 200, 201),
    ],
)
def test_member_access_permissions_are_enforced(access_role, read_status, write_status):
    with given(_GIVEN) as context:
        there_is_a_user(
            email="member@example.com", role=OrganizationRole.MEMBER, organization_id=context.organization.id
        )(context)
        there_is_an_access_token_for_user()(context)
        if access_role:
            there_is_agent_access(access_role_id=access_role)(context)
        assert_that(context.client.get(_path(context), headers=_headers(context)).status_code, equal_to(read_status))
        assert_that(_create(context).status_code, equal_to(write_status))
        for suffix, success in [("/apply", 200), ("/preflight", 204)]:
            response = context.client.post(_path(context, suffix), headers=_headers(context), json={})
            assert_that(response.status_code, equal_to(success if write_status == 201 else write_status))


def test_cross_organization_connection_cannot_be_read_or_mutated():
    with given(_GIVEN) as context:
        first = _create(context).json()
        original_path = _path(context)
        there_is_a_user(email="outsider@example.com", organization_id=uuid4(), role=OrganizationRole.OWNER)(context)
        there_is_an_access_token_for_user()(context)
        there_is_an_agent(status=AgentStatus.STOPPED)(context)
        assert_that(context.client.get(original_path, headers=_headers(context)).status_code, equal_to(403))
        response = context.client.patch(
            _path(context, "/" + first["id"]), headers=_headers(context), json={"name": "steal"}
        )
        assert_that(response.status_code, equal_to(404))


def test_read_only_api_key_can_list_but_cannot_mutate():
    with given(_GIVEN) as context:
        key = context.client.post(
            "/api/v1/auth/me/api-keys", headers=_headers(context), json={"name": "Read API", "access_mode": "READ_ONLY"}
        ).json()["token"]
        context.access_token = key
        assert_that(context.client.get(_path(context), headers=_headers(context)).status_code, equal_to(200))
        assert_that(_create(context).status_code, equal_to(403))
        for suffix in ["/apply", "/preflight"]:
            assert_that(
                context.client.post(_path(context, suffix), headers=_headers(context), json={}).status_code,
                equal_to(403),
            )


def test_invalid_payload_never_echoes_nested_credential_input():
    with given(_GIVEN) as context:
        response = context.client.post(
            _path(context),
            headers=_headers(context),
            json={
                "name": "Invalid",
                "base_url": "https://api.example.com/v1",
                "auth": {"type": "unsupported", "token": "sensitive-fixture-value"},
            },
        )
        assert_that(response.status_code, equal_to(422))
        assert_that(response.text, not_(contains_string("sensitive-fixture-value")))


def test_start_and_apply_restart_replace_custom_api_credentials_without_persisting_them_in_configmap():
    from api.infrastructure.kubernetes.client import KubernetesClient

    with given(_GIVEN) as context:
        created = _create(context).json()
        agent_path = _path(context).removesuffix("/custom-api-connections")
        started = context.client.post(agent_path + "/start", headers=_headers(context))
        assert_that(started.status_code, equal_to(200))
        k8s = context.injector.get(KubernetesClient)
        direct_env = json.dumps(k8s.create_secret.call_args.args[1].string_data)
        assert_that(direct_env, contains_string("fixture-private-token"))
        response = context.client.post(
            _path(context, "/" + created["id"] + "/apply"),
            headers=_headers(context),
            json={"isolated": True, "restart": True},
        )
        assert_that(response.status_code, equal_to(200))
        isolated_env = json.dumps(k8s.create_secret.call_args.args[1].string_data)
        assert_that(isolated_env, not_(contains_string("fixture-private-token")))
        config_map = k8s.create_config_map.call_args.args[1].data
        assert_that(json.dumps(config_map), not_(contains_string("fixture-private-token")))
        assert_that("agentbarn_api.py" in config_map, is_(False))
        assert_that(config_map["AGENTS.md"], contains_string("aai-cli --profile custom-api-CONNECTION_ID"))
        profiles = tomllib.loads(config_map["aai-cli-config.toml"])["profiles"]
        assert_that(profiles["custom-api-inventory"]["auth_type"], equal_to("none"))
        assert_that(config_map["aai-cli-setup.sh"], contains_string("custom-api-secrets.list"))


def test_failed_preflight_does_not_stop_agent_or_replace_credentials():
    from unittest.mock import patch

    from api.domains.agents.service import AgentService
    from api.infrastructure.kubernetes.client import KubernetesClient

    with given(_GIVEN) as context:
        created = _create(context).json()
        context.agent.status = AgentStatus.RUNNING
        context.injector.get(AgentRepository).save(context.agent)
        service = context.injector.get(AgentService)
        with patch.object(service, "_provision_and_start", side_effect=ValueError("fixture secret must not be echoed")):
            response = context.client.post(
                _path(context, "/" + created["id"] + "/apply"),
                headers=_headers(context),
                json={"isolated": True, "restart": True},
            )
        assert_that(response.status_code, equal_to(400))
        assert_that(response.text, not_(contains_string("fixture secret")))
        assert_that(context.injector.get(KubernetesClient).delete_deployment.called, is_(False))
        assert_that(
            context.injector.get(CustomApiRepository).runtime_connections(context.agent.id)[0].isolated, is_(False)
        )


def test_duplicate_identifier_does_not_stop_running_agent():
    from api.infrastructure.kubernetes.client import KubernetesClient

    with given(_GIVEN) as context:
        assert_that(_create(context).status_code, equal_to(201))
        context.agent.status = AgentStatus.RUNNING
        context.injector.get(AgentRepository).save(context.agent)
        response = context.client.post(
            _path(context),
            headers=_headers(context),
            json={
                "name": "INVENTORY",
                "base_url": "https://api.example.com/v1",
                "restart": True,
            },
        )
        assert_that(response.status_code, equal_to(409))
        assert_that(context.injector.get(KubernetesClient).delete_deployment.called, is_(False))
        assert_that(
            context.injector.get(AgentRepository).get_by_id(context.agent.id).status, equal_to(AgentStatus.RUNNING)
        )


@pytest.mark.parametrize("suffix", ["/apply", "/preflight"])
def test_invalid_bulk_changes_do_not_stop_or_partially_save(suffix):
    from api.infrastructure.kubernetes.client import KubernetesClient

    with given(_GIVEN) as context:
        original = _create(context).json()
        context.agent.status = AgentStatus.RUNNING
        context.injector.get(AgentRepository).save(context.agent)
        response = context.client.post(
            _path(context, suffix),
            headers=_headers(context),
            json={
                "creates": [
                    {"name": name, "base_url": "https://api.example.com/v1"}
                    for name in ["Inventory API", "Inventory/API"]
                ],
                "updates": [{"id": original["id"], "data": {"name": "Must not persist"}}],
                "restart": True,
            },
        )
        assert_that(response.status_code, equal_to(409))
        assert_that(context.injector.get(KubernetesClient).delete_deployment.called, is_(False))
        assert_that(
            context.injector.get(AgentRepository).get_by_id(context.agent.id).status, equal_to(AgentStatus.RUNNING)
        )
        rows = context.injector.get(CustomApiRepository).runtime_connections(context.agent.id)
        assert_that(rows, has_length(1))
        assert_that(rows[0].name, equal_to(original["name"]))


def test_successful_bulk_preflight_leaves_running_agent_and_connections_unchanged():
    from api.infrastructure.kubernetes.client import KubernetesClient

    with given(_GIVEN) as context:
        original = _create(context).json()
        context.agent.status = AgentStatus.RUNNING
        context.injector.get(AgentRepository).save(context.agent)
        response = context.client.post(
            _path(context, "/preflight"),
            headers=_headers(context),
            json={
                "updates": [{"id": original["id"], "data": {"name": "Preview only"}}],
                "creates": [{"name": "Reporting", "base_url": "https://api.example.com/v1"}],
                "restart": True,
            },
        )
        assert_that(response.status_code, equal_to(204))
        assert_that(response.content, equal_to(b""))
        assert_that(context.client.get(_path(context), headers=_headers(context)).json(), equal_to([original]))
        assert_that(
            context.injector.get(AgentRepository).get_by_id(context.agent.id).status, equal_to(AgentStatus.RUNNING)
        )
        k8s = context.injector.get(KubernetesClient)
        assert_that(k8s.delete_deployment.called, is_(False))
        assert_that(k8s.create_deployment.called, is_(False))


@pytest.mark.parametrize("suffix", ["/apply", "/preflight"])
def test_bulk_rejects_connection_updated_and_deleted_together(suffix):
    with given(_GIVEN) as context:
        original = _create(context).json()
        response = context.client.post(
            _path(context, suffix),
            headers=_headers(context),
            json={
                "updates": [{"id": original["id"], "data": {"name": "Conflicting update"}}],
                "deletes": [original["id"]],
            },
        )
        assert_that(response.status_code, equal_to(422))
        assert_that(context.client.get(_path(context), headers=_headers(context)).json(), equal_to([original]))


def test_bulk_apply_restarts_once_and_keeps_secrets_private():
    from api.infrastructure.kubernetes.client import KubernetesClient

    with given(_GIVEN) as context:
        context.agent.status = AgentStatus.RUNNING
        context.injector.get(AgentRepository).save(context.agent)
        response = context.client.post(
            _path(context, "/apply"),
            headers=_headers(context),
            json={
                "creates": [
                    {
                        "name": name,
                        "base_url": "https://api.example.com/v1",
                        "auth": {"type": "bearer", "token": "fixture-batch-secret"},
                    }
                    for name in ["Inventory API", "Reporting API"]
                ],
                "restart": True,
            },
        )
        assert_that(response.status_code, equal_to(200))
        assert_that(response.json(), has_length(2))
        assert_that(response.text, not_(contains_string("fixture-batch-secret")))
        k8s = context.injector.get(KubernetesClient)
        # Start also removes any stale Deployment before creating the new one.
        assert_that(k8s.delete_deployment.call_count, equal_to(2))
        assert_that(k8s.create_deployment.call_count, equal_to(1))


def test_bulk_preflight_failure_does_not_write_or_stop():
    from unittest.mock import patch

    from api.domains.agents.service import AgentService
    from api.infrastructure.kubernetes.client import KubernetesClient

    with given(_GIVEN) as context:
        original = _create(context).json()
        context.agent.status = AgentStatus.RUNNING
        context.injector.get(AgentRepository).save(context.agent)
        service = context.injector.get(AgentService)
        with patch.object(service, "_provision_and_start", side_effect=ValueError("private fixture failure")):
            response = context.client.post(
                _path(context, "/apply"),
                headers=_headers(context),
                json={
                    "deletes": [original["id"]],
                    "creates": [{"name": "Replacement", "base_url": "https://api.example.com/v1"}],
                    "restart": True,
                },
            )
        assert_that(response.status_code, equal_to(400))
        assert_that(response.text, not_(contains_string("private fixture")))
        assert_that(context.injector.get(KubernetesClient).delete_deployment.called, is_(False))
        rows = context.injector.get(CustomApiRepository).runtime_connections(context.agent.id)
        assert_that([str(row.id) for row in rows], equal_to([original["id"]]))


def test_bulk_apply_updates_deletes_and_reuses_deleted_identifier():
    with given(_GIVEN) as context:
        original = _create(context).json()
        other = _create(context, "reporting").json()
        response = context.client.post(
            _path(context, "/apply"),
            headers=_headers(context),
            json={
                "deletes": [original["id"]],
                "updates": [{"id": other["id"], "data": {"name": "Renamed reporting"}}],
                "creates": [{"name": "Inventory", "base_url": "https://other.example.com/v2"}],
            },
        )
        assert_that(response.status_code, equal_to(200))
        rows = {row["slug"]: row for row in response.json()}
        assert_that(sorted(rows), equal_to(["inventory", "reporting"]))
        assert_that(rows["inventory"]["id"], not_(equal_to(original["id"])))
        assert_that(rows["reporting"]["name"], equal_to("Renamed reporting"))


@pytest.mark.parametrize("suffix", ["/apply", "/preflight"])
def test_bulk_targets_cannot_reference_another_agent(suffix):
    with given(_GIVEN) as context:
        original = _create(context).json()
        there_is_an_agent(status=AgentStatus.STOPPED)(context)
        response = context.client.post(
            _path(context, suffix), headers=_headers(context), json={"deletes": [original["id"]]}
        )
        assert_that(response.status_code, equal_to(404))


def test_ordinary_header_can_be_cleared_while_saved_secret_is_retained():
    with given(_GIVEN) as context:
        created = _create(context).json()
        response = context.client.patch(
            _path(context, "/" + created["id"]),
            headers=_headers(context),
            json={
                "headers": [
                    {"name": "X-Api-Version", "value": "", "secret": False},
                    {"name": "X-Tenant-Key", "secret": True},
                ]
            },
        )
        assert_that(response.status_code, equal_to(200))
        assert_that(response.json()["headers"][0]["value"], equal_to(""))
        assert_that(response.json()["headers"][1]["value"], none())


def test_gateway_injects_connection_credentials_and_refuses_revoked_generation(monkeypatch):
    from starlette.testclient import TestClient

    from api.domains.custom_api import request as engine
    from api.gateway_app import create_gateway_app

    class Upstream:
        status = 200

        def __init__(self, *_args):
            self.headers = {}

        def request(self, method, path, body=None, headers=None):
            self.headers = headers or {}

        def getresponse(self):
            return self

        def read(self, _limit):
            return json.dumps({"echo": self.headers.get("authorization"), "result": "ok"}).encode()

        def close(self):
            pass

    monkeypatch.setattr(engine, "public_addresses", lambda *_args: ["8.8.8.8"])
    monkeypatch.setattr(engine, "PinnedHTTPSConnection", Upstream)
    with given(_GIVEN) as context:
        assert_that(_create(context, isolated=True).status_code, equal_to(201))
        repository = context.injector.get(CustomApiRepository)
        integrations = context.injector.get(IntegrationRepository)
        rows = repository.runtime_connections(context.agent.id)
        generation = integrations.begin(context.agent.id, connection_snapshot(rows))
        artifacts = materialize_custom_api(
            rows, TEST_ENCRYPTION_KEY, "http://gateway.test", repository, generation.generation
        )
        token = next(value for name, value in artifacts.env.items() if name.endswith("_GATEWAY"))
        context.agent.status = AgentStatus.RUNNING
        context.injector.get(AgentRepository).save(context.agent)
        gateway = TestClient(create_gateway_app(context.injector))
        headers = {"Authorization": "Bearer " + token}
        body = {"url": "https://api.example.com/v1/items"}
        response = gateway.post("/gateway/v1/custom-api/request", headers=headers, json=body)
        assert_that(response.status_code, equal_to(200))
        assert_that(response.json(), equal_to({"status": 200, "body": {"echo": "[REDACTED]", "result": "ok"}}))
        override = gateway.post(
            "/gateway/v1/custom-api/request",
            headers=headers,
            json={**body, "headers": [{"name": "Authorization", "value": "replacement"}]},
        )
        assert_that(override.status_code, equal_to(400))
        integrations.set_state(context.agent.id, "stopped")
        response = gateway.post("/gateway/v1/custom-api/request", headers=headers, json=body)
        assert_that(response.status_code, equal_to(403))


class _TokenIssuingUpstream:
    """A fake pinned connection: a client-credentials token endpoint plus an API that echoes its authorization."""

    exchanges: ClassVar[list[dict]] = []
    api_calls: ClassVar[list[dict]] = []
    reject_api: ClassVar[bool] = False

    def __init__(self, *_args, **_kwargs):
        self.status = 200
        self.body = b""

    def request(self, method, path, body=None, headers=None):
        from urllib.parse import parse_qs

        cls = type(self)
        if path == "/v1/oauth/access_token":
            form = {key: values[0] for key, values in parse_qs((body or b"").decode()).items()}
            cls.exchanges.append({"method": method, "headers": headers, **form})
            if form.get("client_secret") == "fixture-client-secret":
                issued = {"access_token": f"minted-{len(cls.exchanges)}", "token_type": "Bearer", "expires_in": 3600}
                self.body = json.dumps(issued).encode()
            else:
                self.status, self.body = 401, json.dumps({"error": "invalid_client"}).encode()
            return
        cls.api_calls.append(headers or {})
        if cls.reject_api:
            self.status = 401
        self.body = json.dumps({"echo": (headers or {}).get("authorization"), "path": path}).encode()

    def getresponse(self):
        return self

    def read(self, _limit):
        return self.body

    def close(self):
        pass


def test_oauth2_connection_is_isolated_only_verified_on_save_and_authenticated_by_the_gateway(monkeypatch):
    from starlette.testclient import TestClient

    from api.domains.custom_api import request as engine
    from api.gateway_app import create_gateway_app

    class Upstream(_TokenIssuingUpstream):
        exchanges: ClassVar[list[dict]] = []
        api_calls: ClassVar[list[dict]] = []
        reject_api: ClassVar[bool] = False

    upstream = Upstream
    monkeypatch.setattr(engine, "public_addresses", lambda *_args: ["8.8.8.8"])
    monkeypatch.setattr(engine, "PinnedHTTPSConnection", upstream)

    def payload(secret="fixture-client-secret", isolated=True):
        return {
            "name": "Snov.io",
            "base_url": "https://api.snov.io",
            "isolated": isolated,
            "auth": {
                "type": "oauth2_client_credentials",
                "token_url": "https://api.snov.io/v1/oauth/access_token",
                "client_id": "fixture-client-id",
                "client_secret": secret,
            },
        }

    with given(_GIVEN) as context:
        direct = context.client.post(_path(context), headers=_headers(context), json=payload(isolated=False))
        assert_that(direct.status_code, equal_to(422))
        assert_that(direct.json()["detail"], contains_string("isolation"))
        assert_that(upstream.exchanges, has_length(0))

        wrong = context.client.post(_path(context), headers=_headers(context), json=payload(secret="wrong-secret"))
        assert_that(wrong.status_code, equal_to(422))
        assert_that(wrong.json()["detail"], contains_string("HTTP 401"))
        assert_that(wrong.text, not_(contains_string("wrong-secret")))
        assert_that(upstream.exchanges, has_length(1))
        assert_that(upstream.exchanges[0]["headers"]["content-type"], equal_to("application/x-www-form-urlencoded"))

        created = context.client.post(_path(context), headers=_headers(context), json=payload())
        assert_that(created.status_code, equal_to(201))
        assert_that(created.json()["auth_type"], equal_to("oauth2_client_credentials"))
        assert_that(created.json()["auth_token_url"], equal_to("https://api.snov.io/v1/oauth/access_token"))
        assert_that(created.json()["isolated"], is_(True))
        listed = context.client.get(_path(context), headers=_headers(context))
        for text in (created.text, listed.text):
            assert_that(text, not_(contains_string("fixture-client")))
        assert_that(upstream.exchanges, has_length(2))

        # A rename, even one that resends the unchanged auth as the editor does, does not
        # re-verify; a scope change does, and leaving the scope out clears it.
        connection_id = created.json()["id"]
        renamed = context.client.patch(
            _path(context, f"/{connection_id}"),
            headers=_headers(context),
            json={
                "name": "Snov.io outreach",
                "auth": {"type": "oauth2_client_credentials", "token_url": payload()["auth"]["token_url"]},
            },
        )
        assert_that(renamed.status_code, equal_to(200))
        assert_that(upstream.exchanges, has_length(2))
        scoped = context.client.patch(
            _path(context, f"/{connection_id}"),
            headers=_headers(context),
            json={"auth": {**payload()["auth"], "client_secret": None, "client_id": None, "scope": "campaigns"}},
        )
        assert_that(scoped.status_code, equal_to(200))
        assert_that(scoped.json()["auth_scope"], equal_to("campaigns"))
        assert_that(upstream.exchanges, has_length(3))
        assert_that(upstream.exchanges[-1]["scope"], equal_to("campaigns"))
        cleared = context.client.patch(
            _path(context, f"/{connection_id}"),
            headers=_headers(context),
            json={"auth": {"type": "oauth2_client_credentials", "token_url": payload()["auth"]["token_url"]}},
        )
        assert_that(cleared.json()["auth_scope"], is_(none()))
        assert_that(upstream.exchanges, has_length(4))
        assert_that("scope" in upstream.exchanges[-1], is_(False))
        unisolated = context.client.patch(
            _path(context, f"/{connection_id}"), headers=_headers(context), json={"isolated": False}
        )
        assert_that(unisolated.status_code, equal_to(422))
        # The editor's preflight validates the shape only; the token request waits for the save.
        preflight = context.client.post(
            _path(context, "/preflight"), headers=_headers(context), json={"creates": [{**payload(), "name": "Second"}]}
        )
        assert_that(preflight.status_code, equal_to(204))
        assert_that(upstream.exchanges, has_length(4))

        repository = context.injector.get(CustomApiRepository)
        integrations = context.injector.get(IntegrationRepository)
        rows = repository.runtime_connections(context.agent.id)
        generation = integrations.begin(context.agent.id, connection_snapshot(rows))
        artifacts = materialize_custom_api(
            rows, TEST_ENCRYPTION_KEY, "http://gateway.test", repository, generation.generation
        )
        for rendered in artifacts.files.values():
            assert_that(rendered, not_(contains_string("fixture-client")))
        token = next(value for name, value in artifacts.env.items() if name.endswith("_GATEWAY"))
        context.agent.status = AgentStatus.RUNNING
        context.injector.get(AgentRepository).save(context.agent)
        gateway = TestClient(create_gateway_app(context.injector))
        headers = {"Authorization": "Bearer " + token}
        body = {"url": "https://api.snov.io/v1/campaigns"}

        response = gateway.post("/gateway/v1/custom-api/request", headers=headers, json=body)
        assert_that(response.status_code, equal_to(200))
        assert_that(response.json(), equal_to({"status": 200, "body": {"echo": "[REDACTED]", "path": "/v1/campaigns"}}))
        exchanged = len(upstream.exchanges)
        assert_that(upstream.api_calls[-1]["authorization"], equal_to(f"Bearer minted-{exchanged}"))
        gateway.post("/gateway/v1/custom-api/request", headers=headers, json=body)
        assert_that(upstream.exchanges, has_length(exchanged))

        # An upstream 401 drops the cached token, so the next request exchanges again.
        upstream.reject_api = True
        rejected = gateway.post("/gateway/v1/custom-api/request", headers=headers, json=body)
        assert_that(rejected.json()["status"], equal_to(401))
        upstream.reject_api = False
        gateway.post("/gateway/v1/custom-api/request", headers=headers, json=body)
        assert_that(upstream.exchanges, has_length(exchanged + 1))
        assert_that(upstream.api_calls[-1]["authorization"], equal_to(f"Bearer minted-{exchanged + 1}"))
