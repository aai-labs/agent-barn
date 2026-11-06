from unittest.mock import patch
from uuid import uuid7

import pytest

from api.domains.agents.models import AgentStatus, ApolloContent, SecretProvider, decrypt_content, encrypt_content
from api.domains.agents.repository import AgentRepository
from api.domains.custom_api.repository import CustomApiRepository
from api.domains.integrations.repository import IntegrationRepository
from api.domains.shared_credentials.models import SharedCredential
from api.infrastructure.integration_validators.result import IntegrationValidationResult
from api.infrastructure.kubernetes.client import KubernetesClient
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    providers_accept_credentials,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(),
    providers_accept_credentials(),
]


def _base(context):
    return f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}"


def _auth(context):
    return {"Authorization": f"Bearer {context.access_token}"}


def _apply(context, **body):
    return context.client.patch(_base(context), json=body, headers=_auth(context))


def _start(context):
    response = context.client.post(f"{_base(context)}/start", headers=_auth(context))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "RUNNING"
    cluster = context.injector.get(KubernetesClient)
    cluster.reset_mock()
    return cluster


def _secret(key):
    return {"provider": "apollo", "content": {"api_token": key}}


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("failure", ["invalid", "unavailable"])
def test_rejected_credential_keeps_agent_running_and_preserves_all_settings(shared, failure):
    with given(_GIVEN) as context:
        saved = context.client.patch(
            _base(context), json={"secrets": [_secret("previous-key")]}, headers=_auth(context)
        )
        assert saved.status_code == 200, saved.text
        cluster = _start(context)
        repository = context.injector.get(AgentRepository)
        old = repository.get_secret(context.agent.id, SecretProvider.APOLLO)
        assert old is not None
        original_content = old.content
        original_runtime = context.injector.get(IntegrationRepository).runtime(context.agent.id)
        assert original_runtime is not None
        body: dict = {"secrets": [_secret("rejected-key")]}
        if shared:
            credential = SharedCredential(
                organization_id=context.organization.id,
                name="Rejected shared Apollo",
                provider=SecretProvider.APOLLO,
                content=encrypt_content(ApolloContent(api_token="rejected-key"), TEST_ENCRYPTION_KEY),
            )
            context.postgres_delegate.save(credential)
            body = {
                "shared_credentials": [{"shared_credential_id": str(credential.id)}],
                "removed_secret_providers": ["apollo"],
            }
        body.update(
            restart=True,
            policies=[{"provider": "apollo", "isolated": True}],
            custom_api={
                "creates": [{"name": "Example", "base_url": "https://example.com", "auth": {"type": "none"}}],
            },
        )

        def validate(content):
            assert content.api_token == "rejected-key"
            assert repository.get_by_id(context.agent.id).status == AgentStatus.RUNNING
            assert not cluster.delete_deployment.called
            if failure == "unavailable":
                raise RuntimeError("fixture provider unavailable")
            return IntegrationValidationResult(valid=False, error="Invalid API key")

        with when("a running Agent receives a rejected replacement credential"):
            with patch.dict("api.domains.agents.service.PROVIDER_VALIDATORS", {SecretProvider.APOLLO: validate}):
                response = _apply(context, **body)
        with then("validation does not stop it, save any settings, or rotate its runtime"):
            assert response.status_code == (400 if failure == "invalid" else 503), response.text
            detail = response.json()["detail"]
            assert detail["code"] == "INTEGRATION_VALIDATION_FAILED"
            assert detail["provider"] == "apollo"
            assert "Apollo" in detail["message"]
            assert repository.get_by_id(context.agent.id).status == AgentStatus.RUNNING
            assert repository.get_secret(context.agent.id, SecretProvider.APOLLO).content == original_content
            assert not cluster.delete_deployment.called
            assert not cluster.create_deployment.called
            assert (
                context.injector.get(IntegrationRepository).runtime(context.agent.id).generation
                == original_runtime.generation
            )
            assert context.injector.get(CustomApiRepository).runtime_connections(context.agent.id) == []
            assert not context.injector.get(IntegrationRepository).policies(context.agent.id).get(SecretProvider.APOLLO)


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("running,restart", [(True, True), (False, False), (False, True)])
def test_accepted_credential_is_checked_once_before_stop_and_applies_the_whole_form(shared, running, restart):
    with given(_GIVEN) as context:
        cluster = _start(context) if running else context.injector.get(KubernetesClient)
        cluster.reset_mock()
        repository = context.injector.get(AgentRepository)
        calls = []

        def validate(content):
            assert content.api_token == "accepted-key"
            assert not cluster.delete_deployment.called
            assert repository.get_secret(context.agent.id, SecretProvider.APOLLO) is None
            calls.append(content.api_token)
            return IntegrationValidationResult(valid=True)

        credential_body = {"secrets": [_secret("accepted-key")]}
        shared_credential = None
        if shared:
            shared_credential = SharedCredential(
                organization_id=context.organization.id,
                name="Accepted Apollo",
                provider=SecretProvider.APOLLO,
                content=encrypt_content(ApolloContent(api_token="accepted-key"), TEST_ENCRYPTION_KEY),
            )
            context.postgres_delegate.save(shared_credential)
            credential_body = {"shared_credentials": [{"shared_credential_id": str(shared_credential.id)}]}
        with patch.dict("api.domains.agents.service.PROVIDER_VALIDATORS", {SecretProvider.APOLLO: validate}):
            response = _apply(
                context,
                **credential_body,
                restart=restart,
                policies=[{"provider": "apollo", "isolated": True}],
                custom_api={
                    "creates": [
                        {"name": "Example", "base_url": "https://example.com", "auth": {"type": "none"}},
                    ]
                },
            )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == ("RUNNING" if restart else "STOPPED")
        assert calls == ["accepted-key"]
        secret = repository.get_secret(context.agent.id, SecretProvider.APOLLO)
        assert secret is not None
        if shared_credential is not None:
            assert secret.shared_credential_id == shared_credential.id
            assert secret.content is None
        else:
            assert secret.content is not None
            content = decrypt_content(SecretProvider.APOLLO, secret.content, TEST_ENCRYPTION_KEY)
            assert isinstance(content, ApolloContent)
            assert content.api_token == "accepted-key"
        assert context.injector.get(IntegrationRepository).policies(context.agent.id)[SecretProvider.APOLLO]
        assert len(context.injector.get(CustomApiRepository).runtime_connections(context.agent.id)) == 1
        assert cluster.create_deployment.call_count == int(restart)


def test_running_apply_requires_explicit_restart():
    with given(_GIVEN) as context:
        cluster = _start(context)
        response = _apply(context, secrets=[_secret("new-key")])
        assert response.status_code == 409, response.text
        assert not cluster.delete_deployment.called


@pytest.mark.parametrize("empty_custom_api", [False, True])
def test_stopped_credential_save_ignores_unrelated_start_blocker(empty_custom_api):
    with given(_GIVEN) as context:
        repository = context.injector.get(AgentRepository)
        agent = repository.get_by_id(context.agent.id)
        agent.model = "litellm/openrouter/disallowed/model"
        repository.save(agent)
        context.organization.allowed_models = ["openai/*"]
        context.postgres_delegate.save(context.organization)
        blocked = context.client.post(f"{_base(context)}/start", headers=_auth(context))
        assert blocked.status_code == 400, blocked.text
        assert "allowed model list" in blocked.json()["detail"]
        body = {"secrets": [_secret("accepted-key")], "restart": False, "policies": []}
        if empty_custom_api:
            body["custom_api"] = {"creates": [], "updates": [], "deletes": []}
        response = _apply(context, **body)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "STOPPED"
        content = decrypt_content(
            SecretProvider.APOLLO, repository.get_secret(agent.id, SecretProvider.APOLLO).content, TEST_ENCRYPTION_KEY
        )
        assert isinstance(content, ApolloContent)
        assert content.api_token == "accepted-key"
        assert not context.injector.get(KubernetesClient).create_deployment.called


def test_apply_while_lifecycle_lock_is_held_is_rejected():
    with given(_GIVEN) as context:
        cluster = _start(context)
        with context.injector.get(AgentRepository).lifecycle_lock(context.agent.id) as acquired:
            assert acquired
            response = _apply(context, secrets=[_secret("new-key")], restart=True)
        assert response.status_code == 409, response.text
        assert not cluster.delete_deployment.called


def test_apply_cannot_target_another_organizations_agent():
    from api.domains.organizations.models import Organization

    with given(_GIVEN) as context:
        other = Organization(name="Another organization")
        context.postgres_delegate.save(other)
        repository = context.injector.get(AgentRepository)
        agent = repository.get_by_id(context.agent.id)
        agent.organization_id = other.id
        repository.save(agent)
        response = _apply(context, secrets=[_secret("new-key")], restart=True)
        assert response.status_code == 404, response.text
        assert repository.get_secret(agent.id, SecretProvider.APOLLO) is None


@pytest.mark.parametrize("permission", ["agent.update", "agent.secret.manage", "agent.lifecycle.manage"])
def test_apply_requires_each_permission_before_validation_or_stop(permission):
    from api.domains.rbac.catalog import PERMISSION_ID_BY_KEY, PermissionKey
    from api.domains.rbac.models import AgentAccessRole, AgentAccessRolePermission
    from api.domains.users.organization_users.models import OrganizationRole
    from api.tests.steps.agent import there_is_agent_access

    with given(_GIVEN) as context:
        cluster = _start(context)
        membership = context.organization_user
        membership.role = OrganizationRole.MEMBER
        context.postgres_delegate.save(membership)
        role = AgentAccessRole(organization_id=context.organization.id, name="Limited integrations", is_system=False)
        context.postgres_delegate.save(role)
        for allowed in {
            PermissionKey.AGENT_READ,
            PermissionKey.AGENT_UPDATE,
            PermissionKey.AGENT_SECRET_MANAGE,
            PermissionKey.AGENT_LIFECYCLE_MANAGE,
        } - {PermissionKey(permission)}:
            context.postgres_delegate.save(
                AgentAccessRolePermission(role_id=role.id, permission_id=PERMISSION_ID_BY_KEY[allowed])
            )
        there_is_agent_access(access_role_id=role.id)(context)
        with patch.dict(
            "api.domains.agents.service.PROVIDER_VALIDATORS",
            {SecretProvider.APOLLO: lambda _: pytest.fail("Unauthorized provider call")},
        ):
            response = _apply(context, secrets=[_secret("new-key")], restart=True)
        assert response.status_code == 403, response.text
        assert not cluster.delete_deployment.called
        assert context.injector.get(AgentRepository).get_by_id(context.agent.id).status == AgentStatus.RUNNING


@pytest.mark.parametrize(
    "body,code",
    [
        ({"policies": [{"provider": "apollo", "isolated": True}]}, 404),
        (
            {
                "secrets": [_secret("key")],
                "policies": [{"provider": "apollo", "isolated": True}, {"provider": "apollo", "isolated": False}],
            },
            422,
        ),
        ({"secrets": [_secret("key"), _secret("duplicate")]}, 422),
        ({"name": "Unrelated change"}, 422),
        (
            {
                "secrets": [_secret("key")],
                "custom_api": {"updates": [{"id": str(uuid7()), "data": {"name": "Missing"}}]},
            },
            404,
        ),
    ],
)
def test_invalid_mixed_requests_do_not_stop_the_agent(body, code):
    with given(_GIVEN) as context:
        cluster = _start(context)
        response = _apply(context, **body, restart=True)
        assert response.status_code == code, response.text
        assert not cluster.delete_deployment.called
        assert context.injector.get(AgentRepository).get_by_id(context.agent.id).status == AgentStatus.RUNNING


def test_runtime_preflight_failure_keeps_previous_credentials_and_agent_running():
    from fastapi import HTTPException

    from api.domains.agents.service import AgentService

    with given(_GIVEN) as context:
        cluster = _start(context)
        with patch.object(
            AgentService, "_provision_and_start", side_effect=HTTPException(400, "Invalid runtime configuration")
        ):
            response = _apply(context, secrets=[_secret("new-key")], restart=True)
        assert response.status_code == 400, response.text
        repository = context.injector.get(AgentRepository)
        assert repository.get_by_id(context.agent.id).status == AgentStatus.RUNNING
        assert repository.get_secret(context.agent.id, SecretProvider.APOLLO) is None
        assert not cluster.delete_deployment.called


def test_multiple_changed_credentials_report_the_failing_provider_without_saving_the_accepted_one():
    with given(_GIVEN) as context:
        cluster = _start(context)
        validated = []

        def accept_github(content):
            validated.append("github")
            return IntegrationValidationResult(valid=True)

        def reject_apollo(content):
            validated.append("apollo")
            return IntegrationValidationResult(valid=False, error="Invalid API key")

        with patch.dict(
            "api.domains.agents.service.PROVIDER_VALIDATORS",
            {
                SecretProvider.GITHUB: accept_github,
                SecretProvider.APOLLO: reject_apollo,
            },
        ):
            response = _apply(
                context,
                restart=True,
                secrets=[
                    {
                        "provider": "github",
                        "content": {"token": "fixture-token", "owner": "acme", "org": "acme", "repos": []},
                    },
                    _secret("rejected-key"),
                ],
            )
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == {
            "code": "INTEGRATION_VALIDATION_FAILED",
            "provider": "apollo",
            "message": "Apollo credential: Invalid API key",
        }
        assert validated == ["github", "apollo"]
        repository = context.injector.get(AgentRepository)
        assert repository.get_by_id(context.agent.id).status == AgentStatus.RUNNING
        assert repository.get_secret(context.agent.id, SecretProvider.GITHUB) is None
        assert repository.get_secret(context.agent.id, SecretProvider.APOLLO) is None
        assert not cluster.delete_deployment.called
