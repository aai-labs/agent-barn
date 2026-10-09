import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from fastapi import status
from hamcrest import assert_that, equal_to, is_, none
from sqlalchemy import inspect
from sqlmodel import Session, col, select

from api.core.config import Config as AppConfig
from api.domains.agents.models import (
    Agent,
    AgentSecret,
    AgentStatus,
    SecretProvider,
    SharePointContent,
    encrypt_content,
)
from api.domains.agents.repository import AgentRepository
from api.domains.agents.service import AgentService
from api.domains.credential_gateway.forwarding import UpstreamForwarder
from api.domains.credential_gateway.models import GatewayToken
from api.domains.credential_gateway.service import CredentialGatewayService, ForwardRequest, GatewayTokenRejected
from api.domains.integrations.models import AgentIntegrationIsolation
from api.domains.integrations.repository import IntegrationRepository
from api.domains.organizations.models import Organization
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import AuthorizationScope
from api.domains.shared_credentials.models import SharedCredential
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.kubernetes.client import KubernetesClient
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_gateway_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_GITHUB = {"token": "ghp_isolation_fixture", "owner": "acme", "org": "acme", "repos": []}
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
    prepare_gateway_server(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(),
]


def _base(context) -> str:
    return f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}"


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _patch(context, body: dict) -> dict:
    response = context.client.patch(_base(context), json=body, headers=_auth(context))
    assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
    return response.json()


def _policy(context) -> AgentIntegrationIsolation | None:
    with Session(context.postgres_delegate.engine) as session:
        return session.exec(
            select(AgentIntegrationIsolation).where(AgentIntegrationIsolation.agent_id == context.agent.id)
        ).first()


def _require_policy(context) -> AgentIntegrationIsolation:
    policy = _policy(context)
    assert policy is not None
    return policy


def _apply(context, isolated: bool, *, restart: bool = False):
    return context.client.put(
        f"{_base(context)}/integrations/github/isolation",
        json={"isolated": isolated, "restart": restart},
        headers=_auth(context),
    )


def test_stopped_apply_does_not_start_and_preflight_has_no_runtime_side_effects():
    with given(_GIVEN) as context:
        _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        cluster = context.injector.get(KubernetesClient)
        cluster.reset_mock()
        response = _apply(context, True)
        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(response.json()["status"], equal_to("STOPPED"))
        assert_that(bool(response.json()["secrets"][0]["isolation"]["applied"] is None), is_(True))
        assert_that(bool(_require_policy(context).isolated), is_(True))
        assert_that(bool(not cluster.create_deployment.called), is_(True))
        assert_that(bool(not cluster.delete_deployment.called), is_(True))
        assert_that(bool(context.injector.get(IntegrationRepository).runtime(context.agent.id) is None), is_(True))


@pytest.mark.parametrize("agent_status", [AgentStatus.STOPPED, AgentStatus.RUNNING])
@pytest.mark.parametrize("restart", [False, True])
def test_managed_update_refuses_isolation_without_policy_or_runtime_changes(agent_status, restart):
    with given(_GIVEN) as context:
        _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        assert_that(_apply(context, False).status_code, equal_to(200))
        repository = context.injector.get(AgentRepository)
        agent = repository.get_by_id(context.agent.id)
        assert agent is not None
        agent.status = agent_status
        repository.save(agent)
        repository.claim_managed_update(agent.id)
        cluster = context.injector.get(KubernetesClient)
        cluster.reset_mock()
        service = context.injector.get(AgentService)
        with patch.object(service, "_provision_and_start") as provision:
            response = _apply(context, True, restart=restart)
        assert_that(response.status_code, equal_to(409), response.text)
        assert_that(bool(_require_policy(context).isolated), is_(False))
        provision.assert_not_called()
        cluster.create_deployment.assert_not_called()
        cluster.delete_deployment.assert_not_called()


def test_running_mode_changes_require_restart_and_rotate_source_bound_tokens():
    with given(_GIVEN) as context:
        _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        response = context.client.post(f"{_base(context)}/start", headers=_auth(context))
        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(bool(response.json()["secrets"][0]["isolation"]["applied"] is False), is_(True))
        assert_that(_apply(context, True).status_code, equal_to(409))
        response = _apply(context, True, restart=True)
        assert_that(response.status_code, equal_to(200), response.text)
        metadata = response.json()["secrets"][0]["isolation"]
        assert_that(bool(metadata["applied"] is True and metadata["pending"] is False), is_(True))
        first_generation = metadata["generation"]
        cluster = context.injector.get(KubernetesClient)
        secret = cluster.create_secret.call_args.args[1].string_data
        assert_that(bool(str(_GITHUB["token"]) not in str(secret)), is_(True))
        token = secret["AF_GATEWAY_TOKEN_GITHUB"]
        gateway = context.injector.get(CredentialGatewayService)
        assert_that(gateway.resolve(f"Bearer {token}").agent_id, equal_to(context.agent.id))
        response = _apply(context, False, restart=True)
        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(bool(response.json()["secrets"][0]["isolation"]["applied"] is False), is_(True))
        assert_that(
            cluster.create_secret.call_args.args[1].string_data["AAI_SECRET_GITHUB_TOKEN"], equal_to(_GITHUB["token"])
        )
        with pytest.raises(GatewayTokenRejected):
            gateway.resolve(f"Bearer {token}")
        response = _apply(context, True, restart=True)
        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(bool(response.json()["secrets"][0]["isolation"]["generation"] != first_generation), is_(True))
        with pytest.raises(GatewayTokenRejected):
            gateway.resolve(f"Bearer {token}")


def test_failed_preflight_preserves_the_running_mode_and_tokens():
    with given(_GIVEN) as context:
        _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        assert_that(_apply(context, True, restart=True).status_code, equal_to(200))
        cluster = context.injector.get(KubernetesClient)
        token = cluster.create_secret.call_args.args[1].string_data["AF_GATEWAY_TOKEN_GITHUB"]
        binding = context.injector.get(AgentRepository).get_secret(context.agent.id, SecretProvider.GITHUB)
        binding.content = "corrupt ciphertext"
        context.postgres_delegate.save(binding)
        cluster.reset_mock()
        response = _apply(context, False, restart=True)
        assert_that(bool(response.status_code >= 400), is_(True))
        assert_that(bool(_require_policy(context).isolated), is_(True))
        assert_that(bool(not cluster.delete_deployment.called), is_(True))
        assert_that(
            context.injector.get(CredentialGatewayService).resolve(f"Bearer {token}").agent_id,
            equal_to(context.agent.id),
        )


def test_failed_start_retains_intent_without_claiming_applied_and_can_retry():
    with given(_GIVEN) as context:
        _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        assert_that(_apply(context, False, restart=True).status_code, equal_to(200))
        cluster = context.injector.get(KubernetesClient)
        cluster.create_deployment.side_effect = RuntimeError("fixture deployment failure")
        response = _apply(context, True, restart=True)
        assert_that(response.status_code, equal_to(500), response.text)
        assert_that(bool(_require_policy(context).isolated), is_(True))
        response = context.client.get(_base(context), headers=_auth(context))
        assert_that(response.json()["status"], equal_to("ERROR"))
        assert_that(bool(response.json()["secrets"][0]["isolation"]["last_verified"] is False), is_(True))
        assert_that(bool(response.json()["secrets"][0]["isolation"]["applied"] is None), is_(True))
        cluster.create_deployment.side_effect = None
        response = _apply(context, True, restart=True)
        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(bool(response.json()["secrets"][0]["isolation"]["applied"] is True), is_(True))


def test_slow_start_returns_provisioned_then_readiness_verifies_without_a_deadline():
    with given(_GIVEN) as context:
        _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        cluster = context.injector.get(KubernetesClient)
        cluster.get_pod_readiness.return_value = ("initializing", None)
        response = _apply(context, True, restart=True)
        assert_that(response.status_code, equal_to(200), response.text)
        metadata = response.json()["secrets"][0]["isolation"]
        assert_that(metadata["applied"], is_(none()))
        assert_that(metadata["generation"] is not None, is_(True))
        assert_that(
            context.injector.get(IntegrationRepository).runtime(context.agent.id).state, equal_to("provisioned")
        )
        cluster.delete_deployment.reset_mock()
        for _ in range(3):
            response = context.client.get(_base(context), headers=_auth(context))
            assert_that(response.json()["status"], equal_to("RUNNING"))
            assert_that(response.json()["secrets"][0]["isolation"]["applied"], is_(none()))
        cluster.delete_deployment.assert_not_called()
        cluster.get_pod_readiness.return_value = ("ready", None)
        response = context.client.get(_base(context), headers=_auth(context))
        assert_that(response.json()["secrets"][0]["isolation"]["applied"], is_(True))


def test_crashed_startup_is_recorded_after_a_provisioned_response():
    with given(_GIVEN) as context:
        _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        cluster = context.injector.get(KubernetesClient)
        cluster.get_pod_readiness.return_value = ("initializing", None)
        assert_that(_apply(context, True, restart=True).status_code, equal_to(200))
        token = cluster.create_secret.call_args.args[1].string_data["AF_GATEWAY_TOKEN_GITHUB"]
        cluster.get_pod_readiness.return_value = ("crashed", "CrashLoopBackOff")
        cluster.runtime_has_exited.return_value = True
        cluster.delete_deployment.reset_mock()
        with context.injector.get(AgentRepository).lifecycle_lock(context.agent.id) as acquired:
            assert_that(acquired, is_(True))
            response = context.client.get(_base(context), headers=_auth(context))
            assert_that(response.json()["status"], equal_to("RUNNING"))
            cluster.delete_deployment.assert_not_called()
        response = context.client.get(_base(context), headers=_auth(context))
        assert_that(response.json()["status"], equal_to("ERROR"))
        assert_that(response.json()["secrets"][0]["isolation"]["applied"], is_(none()))
        assert_that(context.injector.get(IntegrationRepository).runtime(context.agent.id).state, equal_to("failed"))
        with pytest.raises(GatewayTokenRejected):
            context.injector.get(CredentialGatewayService).resolve(f"Bearer {token}")


def test_a_stale_ready_observation_cannot_overwrite_stopping_state():
    with given(_GIVEN) as context:
        _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        cluster = context.injector.get(KubernetesClient)
        cluster.get_pod_readiness.return_value = ("initializing", None)
        assert_that(_apply(context, True, restart=True).status_code, equal_to(200))
        repository = context.injector.get(IntegrationRepository)
        runtime = repository.runtime(context.agent.id)

        def ready_while_stopping(*_):
            repository.set_state(context.agent.id, "stopping", runtime.generation)
            return "ready", None

        cluster.get_pod_readiness.side_effect = ready_while_stopping
        response = context.client.get(_base(context), headers=_auth(context))
        assert_that(response.json()["secrets"][0]["isolation"]["applied"], is_(none()))
        assert_that(repository.runtime(context.agent.id).state, equal_to("stopping"))


@pytest.mark.parametrize(
    "reason", ["ErrImagePull", "ImagePullBackOff", "CreateContainerConfigError", "CreateContainerError"]
)
@pytest.mark.parametrize("read_path", ["", "/healthz"])
def test_retryable_pod_startup_errors_never_trigger_lifecycle_teardown(reason, read_path):
    with given(_GIVEN) as context:
        _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        cluster = context.injector.get(KubernetesClient)
        cluster.get_pod_readiness.return_value = ("initializing", None)
        assert_that(_apply(context, True, restart=True).status_code, equal_to(200))
        token = cluster.create_secret.call_args.args[1].string_data["AF_GATEWAY_TOKEN_GITHUB"]
        cluster.delete_deployment.reset_mock()
        cluster.get_pod_readiness.return_value = ("crashed", reason)
        response = context.client.get(f"{_base(context)}{read_path}", headers=_auth(context))
        assert_that(response.status_code, equal_to(200))
        assert_that(context.injector.get(AgentRepository).get_by_id(context.agent.id).status.value, equal_to("RUNNING"))
        assert_that(
            context.injector.get(IntegrationRepository).runtime(context.agent.id).state, equal_to("provisioned")
        )
        assert_that(
            context.injector.get(CredentialGatewayService).resolve(f"Bearer {token}").agent_id,
            equal_to(context.agent.id),
        )
        cluster.delete_deployment.assert_not_called()


def test_normal_start_is_saved_as_the_previous_verified_mode_before_transition():
    with given(_GIVEN) as context:
        _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        cluster = context.injector.get(KubernetesClient)
        cluster.get_pod_readiness.return_value = ("initializing", None)
        assert_that(context.client.post(f"{_base(context)}/start", headers=_auth(context)).status_code, equal_to(200))
        # No intervening detail view records readiness.
        cluster.get_pod_readiness.return_value = ("ready", None)
        cluster.create_deployment.side_effect = RuntimeError("fixture failure of the replacement")
        assert_that(_apply(context, True, restart=True).status_code, equal_to(500))
        response = context.client.get(_base(context), headers=_auth(context))
        assert_that(response.json()["secrets"][0]["isolation"]["last_verified"], is_(False))


def test_transition_lock_and_tenant_authorization_apply_to_the_writer():
    with given(_GIVEN) as context:
        _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        with context.injector.get(AgentRepository).lifecycle_lock(context.agent.id) as acquired:
            assert_that(bool(acquired), is_(True))
            assert_that(_apply(context, True).status_code, equal_to(409))
        membership = context.organization_user
        membership.role = OrganizationRole.MEMBER
        context.postgres_delegate.save(membership)
        assert_that(_apply(context, True).status_code, equal_to(404))


def test_platform_firecrawl_is_source_bound_and_never_inherited_by_a_stored_token():
    with given(_GIVEN) as context:
        config = context.injector.get(AppConfig)
        config.agent_firecrawl_api_key = "fc-platform-fixture"
        config.agent_firecrawl_base_url = "https://configured.firecrawl.example/v1"
        url = f"{_base(context)}/integrations/firecrawl/isolation"
        response = context.client.put(url, json={"isolated": True, "restart": True}, headers=_auth(context))
        assert_that(response.status_code, equal_to(200), response.text)
        metadata = response.json()["secrets"][0]
        assert_that(metadata["source"], equal_to("platform_default"))
        assert_that(bool(metadata["isolation"]["applied"] is True), is_(True))
        cluster = context.injector.get(KubernetesClient)
        env = cluster.create_secret.call_args.args[1].string_data
        assert_that(bool(config.agent_firecrawl_api_key not in str(env)), is_(True))
        token = env["AF_GATEWAY_TOKEN_FIRECRAWL"]
        gateway = context.injector.get(CredentialGatewayService)
        request = ForwardRequest("firecrawl", "scrape", "POST", {}, {}, b"{}")
        upstream = context.injector.get(UpstreamForwarder)
        # Replace only the unrelated network boundary, never source selection.
        with patch.object(upstream, "send") as send:
            gateway.forward(f"Bearer {token}", request)
            assert_that(send.call_args.args[1], equal_to("https://configured.firecrawl.example/v1/scrape"))
            assert_that(send.call_args.kwargs["headers"]["Authorization"], equal_to("Bearer fc-platform-fixture"))
        assert_that(gateway.resolve(f"Bearer {token}").source, equal_to("platform_default"))
        context.client.post(f"{_base(context)}/stop", headers=_auth(context))
        _patch(context, {"secrets": [{"provider": "firecrawl", "content": {"api_key": "fc-stored"}}]})
        with pytest.raises(GatewayTokenRejected):
            gateway.resolve(f"Bearer {token}")


def test_creation_defaults_direct_without_claiming_an_applied_runtime_mode():
    with given(_GIVEN) as context:
        before = context.agent.running_config_digest
        with when("I configure GitHub"):
            body = _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        with then("intent is persisted but no switch or applied mode is advertised"):
            metadata = body["secrets"][0]["isolation"]
            assert_that(metadata["desired"], is_(False))
            assert_that(metadata["supported_modes"], equal_to(["direct", "isolated"]))
            assert_that(metadata["switch_available"], is_(True))
            assert_that(metadata["applied"], is_(none()))
            assert_that("Google" in metadata["isolated_description"], is_(False))
            policy = _policy(context)
            assert policy is not None
            assert_that(policy.isolated, is_(False))
            response = context.client.get(_base(context), headers=_auth(context))
            assert_that(response.json()["secrets"][0]["isolation"], equal_to(metadata))
            agent = context.postgres_delegate.find_one(Agent, id=context.agent.id)
            assert_that(bool(agent is not None), is_(True))
            assert_that(agent.running_config_digest, equal_to(before))


def test_replacement_and_shared_attachment_preserve_policy_then_removal_deletes_it():
    with given(_GIVEN) as context:
        _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        original = _policy(context)
        assert original is not None  # Type guard for the setup row.
        # Seed a distinct intent to prove replacement cannot reset the choice.
        original.isolated = False
        context.postgres_delegate.save(original)
        _patch(context, {"secrets": [{"provider": "github", "content": {**_GITHUB, "token": "replacement"}}]})
        response = context.client.post(
            f"/api/v1/organizations/{context.organization.id}/shared-credentials",
            headers=_auth(context),
            json={"provider": "github", "name": "Reusable", "content": _GITHUB},
        )
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        shared_id = response.json()["id"]
        body = _patch(
            context,
            {
                "removed_secret_providers": ["github"],
                "shared_credentials": [{"shared_credential_id": shared_id}],
            },
        )
        assert_that(body["secrets"][0]["isolation"]["desired"], is_(False))
        assert_that(_require_policy(context).id, equal_to(original.id))
        _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        assert_that(_require_policy(context).isolated, is_(False))
        _patch(context, {"removed_secret_providers": ["github"]})
        assert_that(_policy(context), is_(none()))
        _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        assert_that(_require_policy(context).isolated, is_(False))


def test_policy_reads_do_not_bypass_agent_visibility():
    with given(_GIVEN) as context:
        _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        repository = context.injector.get(AgentRepository)
        foreign = Organization(name="Other tenant")
        context.postgres_delegate.save(foreign)
        foreign_scope = AuthorizationScope(organization_id=foreign.id)
        assert_that(repository.get_secret_summaries_for_agents([context.agent.id], foreign_scope), equal_to({}))
        membership = context.organization_user
        membership.role = OrganizationRole.MEMBER
        context.postgres_delegate.save(membership)
        # The fixture Agent has no explicit access or General Access.
        response = context.client.get(_base(context), headers=_auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
        scope = AuthorizationScope(
            organization_id=context.organization.id,
            membership_id=membership.id,
            permission=PermissionKey.AGENT_READ,
        )
        assert_that(repository.get_secret_summaries_for_agents([context.agent.id], scope), equal_to({}))


def test_deleting_shared_credential_cleans_policy_for_deleted_agent():
    with given(_GIVEN) as context:
        base = f"/api/v1/organizations/{context.organization.id}/shared-credentials"
        response = context.client.post(
            base, headers=_auth(context), json={"provider": "github", "name": "Reusable", "content": _GITHUB}
        )
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        shared_id = response.json()["id"]
        _patch(context, {"shared_credentials": [{"shared_credential_id": shared_id}]})
        assert_that(_require_policy(context).isolated, is_(False))
        context.agent.deleted_at = datetime.now(UTC)
        context.postgres_delegate.save(context.agent)
        with when("the shared credential is deleted after the Agent was deleted"):
            response = context.client.delete(f"{base}/{shared_id}", headers=_auth(context))
        with then("both the orphaned binding and its policy are removed"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            assert_that(_policy(context), is_(none()))


def test_backfill_preserves_routes_shared_sources_and_gateway_tokens():
    from api.tests.helpers.integration_credentials import credential_for

    with given(_GIVEN) as context:
        shared = SharedCredential(
            organization_id=context.organization.id, provider="github", name="Shared", content="ciphertext"
        )
        context.postgres_delegate.save(shared)
        for provider in SecretProvider:
            secret = AgentSecret(
                agent_id=context.agent.id,
                provider=provider,
                secret_name=provider.value,
                content=(
                    None
                    if provider == SecretProvider.GITHUB
                    else encrypt_content(credential_for(provider), TEST_ENCRYPTION_KEY)
                ),
                shared_credential_id=shared.id if provider == SecretProvider.GITHUB else None,
            )
            context.postgres_delegate.save(secret)
        there_is_an_agent(deleted=True)(context)
        deleted_agent_id = context.agent.id
        context.postgres_delegate.save(
            AgentSecret(
                agent_id=deleted_agent_id, provider=SecretProvider.GITHUB, secret_name="Deleted", content="ciphertext"
            )
        )
        with Session(context.postgres_delegate.engine) as session:
            live = session.exec(select(Agent).where(col(Agent.deleted_at).is_(None))).first()
            assert live is not None  # Type guard for the setup row.
        gateway = context.injector.get(CredentialGatewayService)
        gateway.issue_for_agent(live.id, live.organization_id, {SecretProvider.GITHUB})
        with Session(context.postgres_delegate.engine) as session:
            token_before = [t.model_dump() for t in session.exec(select(GatewayToken)).all()]
        config = Config(Path(__file__).resolve().parents[2] / "alembic.ini")
        try:
            command.downgrade(config, "e02ebff7a128")
            assert_that(inspect(context.postgres_delegate.engine).has_table("agent_integration_isolation"), is_(False))
            command.upgrade(config, "head")
            with Session(context.postgres_delegate.engine) as session:
                policies = session.exec(select(AgentIntegrationIsolation)).all()
                assert_that(
                    {p.provider: p.isolated for p in policies},
                    equal_to({p.value: p != SecretProvider.SHAREPOINT for p in SecretProvider}),
                )
                assert_that(all(p.agent_id != deleted_agent_id for p in policies), is_(True))
                assert_that([t.model_dump() for t in session.exec(select(GatewayToken)).all()], equal_to(token_before))
        finally:
            command.upgrade(config, "head")


def test_generation_downgrade_requires_stopped_sharepoint_and_retains_latest_rotated_grant():
    from api.domains.agents.models import decrypt_content
    from api.infrastructure.crypto import decrypt_token

    with given(_GIVEN) as context:
        _, secret, _, runtime = _sharepoint_binding(context)
        content = decrypt_content(secret.provider, secret.content, TEST_ENCRYPTION_KEY)
        assert isinstance(content, SharePointContent)
        content.refresh_token = "latest-rotated-downgrade-fixture"
        content.broker_access_token = "cached-access-downgrade-fixture"
        content.broker_expires_at = 1234567890
        content.store_revision = "handoff-revision"
        content.subject_id = "subject-fixture"
        secret.content = encrypt_content(content, TEST_ENCRYPTION_KEY)
        context.postgres_delegate.save(secret)
        config = Config(Path(__file__).resolve().parents[2] / "alembic.ini")
        repository = context.injector.get(IntegrationRepository)
        try:
            with when("an active isolated SharePoint generation exists"):
                with pytest.raises(RuntimeError, match="Stop isolated SharePoint"):
                    command.downgrade(config, "7f20a9c813de")
            with when("that generation has stopped and the schema is contracted"):
                repository.set_state(context.agent.id, "stopped", runtime.generation)
                command.downgrade(config, "7f20a9c813de")
            with then("the strict previous schema receives the latest grant without broker metadata"):
                with Session(context.postgres_delegate.engine) as session:
                    stored = session.get(AgentSecret, secret.id)
                    assert stored is not None and stored.content is not None
                    payload = json.loads(decrypt_token(stored.content, TEST_ENCRYPTION_KEY))
                assert_that(payload["refresh_token"], equal_to("latest-rotated-downgrade-fixture"))
                assert_that(
                    set(payload) & {"broker_access_token", "broker_expires_at", "store_revision", "subject_id"},
                    equal_to(set()),
                )
                assert_that(
                    inspect(context.postgres_delegate.engine).has_table("agent_integration_runtime"), is_(False)
                )
            command.upgrade(config, "head")
            assert_that(_require_policy(context).isolated, is_(True))
        finally:
            command.upgrade(config, "head")


def _sharepoint_binding(context):
    from api.domains.agents.models import encrypt_content
    from api.tests.helpers.integration_credentials import credential_for

    content = credential_for(SecretProvider.SHAREPOINT)
    secret = AgentSecret(
        agent_id=context.agent.id,
        provider=SecretProvider.SHAREPOINT,
        secret_name="SharePoint credential",
        content=encrypt_content(content, TEST_ENCRYPTION_KEY),
    )
    context.injector.get(AgentRepository).delegate.save(secret)
    repository = context.injector.get(IntegrationRepository)
    repository.set_policy(context.agent.id, SecretProvider.SHAREPOINT, True)
    runtime = repository.begin(context.agent.id, {"sharepoint": {"binding_id": str(secret.id), "isolated": True}})
    token = (
        context.injector.get(CredentialGatewayService)
        .issue_for_agent(
            context.agent.id, context.organization.id, {SecretProvider.SHAREPOINT}, generation=runtime.generation
        )[0]
        .value
    )
    return content, secret, token, runtime


def _microsoft_reply(token="graph-temporary", refresh="rotated-service-grant"):
    import httpx
    import jwt

    return httpx.Response(
        200,
        json={
            "access_token": token,
            "refresh_token": refresh,
            "expires_in": 3600,
            "scope": "Sites.Read.All",
            "id_token": jwt.encode(
                {
                    "oid": "sharepoint-account-id",
                    "tid": "22222222-2222-4222-8222-222222222222",
                    "aud": "11111111-1111-4111-8111-111111111111",
                    "preferred_username": "fixture@example.com",
                },
                "fixture-signing-key-at-least-32-characters",
                algorithm="HS256",
            ),
        },
    )


def test_sharepoint_handoff_proves_latest_pvc_grant_and_persists_rotation_before_cleanup():
    import base64
    import json
    import os

    from nacl.bindings import crypto_aead_xchacha20poly1305_ietf_encrypt

    from api.domains.agents.models import decrypt_content

    with given(_GIVEN) as context:
        content, _secret, token, _runtime = _sharepoint_binding(context)
        headers = {"Authorization": f"Bearer {token}"}
        assert_that(context.gateway_client.post("/gateway/v1/token", headers=headers).status_code, equal_to(403))
        key, nonce = os.urandom(32), os.urandom(24)
        ciphertext = crypto_aead_xchacha20poly1305_ietf_encrypt(
            json.dumps(
                {"microsoft.sharepoint_refresh_token": "latest-pvc-grant", "github.token": "unrelated"}
            ).encode(),
            None,
            nonce,
            key,
        )
        body = {
            "marker": content.sign_in_id,
            "key": base64.b64encode(key).decode(),
            "store": json.dumps(
                {
                    "version": 1,
                    "nonce": base64.b64encode(nonce).decode(),
                    "ciphertext": base64.b64encode(ciphertext).decode(),
                }
            ),
        }
        with patch(
            "api.domains.credential_gateway.sharepoint_broker.httpx.post", return_value=_microsoft_reply()
        ) as refresh:
            response = context.gateway_client.post("/gateway/v1/sharepoint/handoff", json=body, headers=headers)
            assert_that(response.status_code, equal_to(204), response.text)
            assert_that(refresh.call_args.kwargs["data"]["refresh_token"], equal_to("latest-pvc-grant"))
            assert_that(bool("client_secret" not in refresh.call_args.kwargs["data"]), is_(True))
            assert_that(
                context.gateway_client.post("/gateway/v1/sharepoint/handoff", json=body, headers=headers).status_code,
                equal_to(204),
            )
            response = context.gateway_client.post("/gateway/v1/token", headers=headers)
            assert_that(response.status_code, equal_to(200), response.text)
            assert_that(response.json()["access_token"], equal_to("graph-temporary"))
            assert_that(bool("rotated-service-grant" not in response.text), is_(True))
            assert_that(refresh.call_count, equal_to(1))
            context.injector.get(IntegrationRepository).set_state(context.agent.id, "ready", _runtime.generation)
            assert_that(
                context.gateway_client.post("/gateway/v1/sharepoint/handoff", json=body, headers=headers).status_code,
                equal_to(204),
            )
            assert_that(refresh.call_count, equal_to(1))
        stored = context.injector.get(AgentRepository).get_secret(context.agent.id, SecretProvider.SHAREPOINT)
        grant = decrypt_content(SecretProvider.SHAREPOINT, stored.content, TEST_ENCRYPTION_KEY)
        assert isinstance(grant, SharePointContent)
        assert_that(grant.refresh_token, equal_to("rotated-service-grant"))
        assert_that(grant.broker_access_token, equal_to("graph-temporary"))
        assert_that(
            bool(
                context.injector.get(IntegrationRepository)
                .runtime(context.agent.id)
                .bindings["sharepoint"]["handoff_complete"]
            ),
            is_(True),
        )
        # Expiry refreshes from the rotated service-side copy, never the original grant.
        with (
            patch(
                "api.domains.credential_gateway.sharepoint_broker.time.time",
                return_value=(grant.broker_expires_at or 0) + 1,
            ),
            patch(
                "api.domains.credential_gateway.sharepoint_broker.httpx.post",
                return_value=_microsoft_reply("next-access", "next-grant"),
            ) as refresh,
        ):
            assert_that(
                context.gateway_client.post("/gateway/v1/token", headers=headers).json()["access_token"],
                equal_to("next-access"),
            )
            assert_that(refresh.call_args.kwargs["data"]["refresh_token"], equal_to("rotated-service-grant"))
        gateway = context.injector.get(CredentialGatewayService)
        gateway.sharepoint_broker.prepare_direct(context.agent.id, context.organization.id)
        grant = decrypt_content(
            SecretProvider.SHAREPOINT,
            context.injector.get(AgentRepository).get_secret(context.agent.id, SecretProvider.SHAREPOINT).content,
            TEST_ENCRYPTION_KEY,
        )
        assert isinstance(grant, SharePointContent)
        assert_that(grant.refresh_token, equal_to("next-grant"))
        assert_that(bool(grant.store_revision and grant.broker_access_token is None), is_(True))
        assert_that(context.gateway_client.post("/gateway/v1/token", headers=headers).status_code, equal_to(403))
        # A new generation cannot use a previous generation's token or import payload.
        context.injector.get(IntegrationRepository).begin(context.agent.id, {})
        assert_that(
            context.gateway_client.post("/gateway/v1/sharepoint/handoff", json=body, headers=headers).status_code,
            equal_to(403),
        )


def test_sharepoint_invalid_handoff_and_invalid_grant_preserve_encrypted_credential():
    import httpx

    with given(_GIVEN) as context:
        content, _secret, token, _runtime = _sharepoint_binding(context)
        headers = {"Authorization": f"Bearer {token}"}
        body = {"marker": content.sign_in_id, "store": "invalid", "key": "invalid"}
        with patch("api.domains.credential_gateway.sharepoint_broker.httpx.post") as refresh:
            assert_that(
                context.gateway_client.post("/gateway/v1/sharepoint/handoff", json=body, headers=headers).status_code,
                equal_to(409),
            )
            refresh.assert_not_called()
        with patch(
            "api.domains.credential_gateway.sharepoint_broker.httpx.post",
            return_value=httpx.Response(400, json={"error": "invalid_grant", "error_description": "sensitive-fixture"}),
        ):
            response = context.gateway_client.post("/gateway/v1/sharepoint/handoff", json={}, headers=headers)
            assert_that(response.status_code, equal_to(409))
            assert_that(bool("sensitive-fixture" not in response.text), is_(True))
        assert_that(
            context.injector.get(AgentRepository).get_secret(context.agent.id, SecretProvider.SHAREPOINT).content,
            equal_to(_secret.content),
        )
        assert_that(
            bool(
                not context.injector.get(IntegrationRepository)
                .runtime(context.agent.id)
                .bindings["sharepoint"]
                .get("handoff_complete")
            ),
            is_(True),
        )


def test_sharepoint_reconnect_wins_over_an_older_pvc_marker():
    with given(_GIVEN) as context:
        content, _secret, token, _runtime = _sharepoint_binding(context)
        headers = {"Authorization": f"Bearer {token}"}
        with patch(
            "api.domains.credential_gateway.sharepoint_broker.httpx.post", return_value=_microsoft_reply()
        ) as refresh:
            response = context.gateway_client.post(
                "/gateway/v1/sharepoint/handoff",
                json={"marker": "older-sign-in", "store": "invalid", "key": "invalid"},
                headers=headers,
            )
            assert_that(response.status_code, equal_to(204))
            assert_that(refresh.call_args.kwargs["data"]["refresh_token"], equal_to(content.refresh_token))
        context.injector.get(IntegrationRepository).set_policy(context.agent.id, SecretProvider.SHAREPOINT, False)
        # Pending intent cannot withdraw an applied generation's authorization.
        assert_that(context.gateway_client.post("/gateway/v1/token", headers=headers).status_code, equal_to(200))


def test_invalid_handoff_validation_never_echoes_store_or_key():
    with given(_GIVEN) as context:
        _, _, token, _ = _sharepoint_binding(context)
        response = context.gateway_client.post(
            "/gateway/v1/sharepoint/handoff",
            json={"store": {"private-store-fixture": "private-key-fixture"}, "key": "private-key-fixture"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert_that(response.status_code, equal_to(422))
        assert_that("private-store-fixture" in response.text, is_(False))
        assert_that("private-key-fixture" in response.text, is_(False))


def test_concurrent_sharepoint_mints_rotate_once_and_share_the_persisted_access_token():
    from concurrent.futures import ThreadPoolExecutor

    from api.domains.agents.models import decrypt_content

    with given(_GIVEN) as context:
        _, secret, token, runtime = _sharepoint_binding(context)
        headers = {"Authorization": f"Bearer {token}"}
        with patch("api.domains.credential_gateway.sharepoint_broker.httpx.post", return_value=_microsoft_reply()):
            assert_that(
                context.gateway_client.post("/gateway/v1/sharepoint/handoff", json={}, headers=headers).status_code,
                equal_to(204),
            )
        secret = context.injector.get(AgentRepository).get_secret(context.agent.id, SecretProvider.SHAREPOINT)
        grant = decrypt_content(secret.provider, secret.content, TEST_ENCRYPTION_KEY)
        assert isinstance(grant, SharePointContent)
        grant.broker_expires_at = 0
        secret.content = encrypt_content(grant, TEST_ENCRYPTION_KEY)
        context.postgres_delegate.save(secret)
        broker = context.injector.get(CredentialGatewayService).sharepoint_broker
        with (
            patch(
                "api.domains.credential_gateway.sharepoint_broker.httpx.post",
                return_value=_microsoft_reply("parallel-access", "parallel-latest-grant"),
            ) as refresh,
            ThreadPoolExecutor(max_workers=6) as workers,
        ):
            with when("six commands request an expired token concurrently"):
                minted = list(
                    workers.map(
                        lambda _: broker.mint(context.agent.id, context.organization.id, runtime.generation), range(6)
                    )
                )
            with then("one refresh rotates the encrypted grant and all commands receive its cached result"):
                assert_that(refresh.call_count, equal_to(1))
                assert_that({value.value for value in minted}, equal_to({"parallel-access"}))
        stored = context.injector.get(AgentRepository).get_secret(context.agent.id, SecretProvider.SHAREPOINT)
        updated = decrypt_content(stored.provider, stored.content, TEST_ENCRYPTION_KEY)
        assert isinstance(updated, SharePointContent)
        assert_that(updated.refresh_token, equal_to("parallel-latest-grant"))


def test_restore_direct_after_incomplete_sharepoint_handoff_preserves_the_pvc_grant():
    from api.tests.helpers.integration_credentials import credential_for

    with given(_GIVEN) as context:
        grant = credential_for(SecretProvider.SHAREPOINT)
        assert isinstance(grant, SharePointContent)
        context.postgres_delegate.save(
            AgentSecret(
                agent_id=context.agent.id,
                provider=SecretProvider.SHAREPOINT,
                secret_name="SharePoint credential",
                content=encrypt_content(grant, TEST_ENCRYPTION_KEY),
            )
        )
        url = f"{_base(context)}/integrations/sharepoint/isolation"
        cluster = context.injector.get(KubernetesClient)
        cluster.create_deployment.side_effect = RuntimeError("fixture failure before handoff")
        assert_that(
            context.client.put(url, json={"isolated": True, "restart": True}, headers=_auth(context)).status_code,
            equal_to(500),
        )
        cluster.create_deployment.side_effect = None
        broker = context.injector.get(CredentialGatewayService).sharepoint_broker
        with patch.object(broker, "prepare_direct", wraps=broker.prepare_direct) as handback:
            response = context.client.put(url, json={"isolated": False, "restart": True}, headers=_auth(context))
            assert_that(response.status_code, equal_to(200), response.text)
            handback.assert_not_called()
        assert_that(response.json()["secrets"][0]["isolation"]["applied"], is_(False))
        assert_that(
            cluster.create_secret.call_args.args[1].string_data["AAI_SHAREPOINT_SIGN_IN_ID"], equal_to(grant.sign_in_id)
        )


def test_default_firecrawl_choice_survives_stored_credential_attachment_and_removal():
    with given(_GIVEN) as context:
        repository = context.injector.get(IntegrationRepository)
        repository.set_policy(context.agent.id, SecretProvider.FIRECRAWL, True, "platform_default")
        _patch(context, {"secrets": [{"provider": "firecrawl", "content": {"api_key": "stored-key"}}]})
        assert_that(bool(repository.policies(context.agent.id)[SecretProvider.FIRECRAWL] is False), is_(True))
        _patch(context, {"removed_secret_providers": ["firecrawl"]})
        assert_that(
            bool(repository.policies(context.agent.id, "platform_default")[SecretProvider.FIRECRAWL] is True), is_(True)
        )


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
@pytest.mark.parametrize("provider", list(SecretProvider))
def test_each_provider_applies_both_directions_in_each_runtime(runtime, provider):
    from api.domains.agents.models import AgentType, encrypt_content
    from api.domains.credential_gateway.models import gateway_token_env_var
    from api.tests.helpers.integration_credentials import credential_for

    with given([*_GIVEN[:-1], there_is_an_agent(agent_type=AgentType(runtime))]) as context:
        grant = credential_for(provider)
        context.postgres_delegate.save(
            AgentSecret(
                agent_id=context.agent.id,
                provider=provider,
                secret_name=provider.value,
                content=encrypt_content(grant, TEST_ENCRYPTION_KEY),
            )
        )
        repository = context.injector.get(IntegrationRepository)
        repository.set_policy(context.agent.id, provider, False)
        cluster = context.injector.get(KubernetesClient)
        url = f"{_base(context)}/integrations/{provider.value}/isolation"
        for isolated in (False, True, False):

            def finish_boot(_namespace, _deployment, selected=isolated):
                if provider == SecretProvider.SHAREPOINT and selected:
                    token = cluster.create_secret.call_args.args[1].string_data[gateway_token_env_var(provider)]
                    with patch(
                        "api.domains.credential_gateway.sharepoint_broker.httpx.post", return_value=_microsoft_reply()
                    ):
                        response = context.gateway_client.post(
                            "/gateway/v1/sharepoint/handoff", json={}, headers={"Authorization": f"Bearer {token}"}
                        )
                        assert_that(response.status_code, equal_to(204), response.text)

            cluster.create_deployment.side_effect = finish_boot
            response = context.client.put(url, json={"isolated": isolated, "restart": True}, headers=_auth(context))
            assert_that(response.status_code, equal_to(200), response.text)
            metadata = response.json()["secrets"][0]["isolation"]
            assert_that(metadata["desired"], is_(isolated))
            assert_that(metadata["applied"], is_(isolated))
            assert_that(metadata["pending"], is_(False))
            environment = cluster.create_secret.call_args.args[1].string_data
            assert_that(gateway_token_env_var(provider) in environment, is_(isolated))
            expected = f"{provider.value}-provider-secret"
            if provider == SecretProvider.SHAREPOINT:
                from api.domains.agents.models import decrypt_content

                current_grant = decrypt_content(
                    provider,
                    context.injector.get(AgentRepository).get_secret(context.agent.id, provider).content,
                    TEST_ENCRYPTION_KEY,
                )
                assert isinstance(current_grant, SharePointContent)
                expected = current_grant.refresh_token
            assert expected is not None
            assert_that(expected in str(environment), is_(not isolated))


@pytest.mark.parametrize(
    "permission", [PermissionKey.AGENT_UPDATE, PermissionKey.AGENT_SECRET_MANAGE, PermissionKey.AGENT_LIFECYCLE_MANAGE]
)
def test_policy_writer_requires_each_permission_before_mutation(permission):
    from api.domains.rbac.catalog import PERMISSION_ID_BY_KEY
    from api.domains.rbac.models import AgentAccessRole, AgentAccessRolePermission
    from api.tests.steps.agent import there_is_agent_access

    with given(_GIVEN) as context:
        _patch(context, {"secrets": [{"provider": "github", "content": _GITHUB}]})
        membership = context.organization_user
        membership.role = OrganizationRole.MEMBER
        context.postgres_delegate.save(membership)
        role = AgentAccessRole(organization_id=context.organization.id, name="Limited isolation role", is_system=False)
        context.postgres_delegate.save(role)
        for allowed in {
            PermissionKey.AGENT_READ,
            PermissionKey.AGENT_UPDATE,
            PermissionKey.AGENT_SECRET_MANAGE,
            PermissionKey.AGENT_LIFECYCLE_MANAGE,
        } - {permission}:
            context.postgres_delegate.save(
                AgentAccessRolePermission(role_id=role.id, permission_id=PERMISSION_ID_BY_KEY[allowed])
            )
        there_is_agent_access(access_role_id=role.id)(context)
        cluster = context.injector.get(KubernetesClient)
        cluster.reset_mock()
        response = _apply(context, True, restart=True)
        assert_that(response.status_code, equal_to(403), response.text)
        assert_that(_require_policy(context).isolated, is_(False))
        assert_that(cluster.delete_deployment.called, is_(False))
        assert_that(cluster.create_deployment.called, is_(False))


def test_sharepoint_import_rejects_another_account_without_replacing_the_grant():
    with given(_GIVEN) as context:
        _content, secret, token, _runtime = _sharepoint_binding(context)
        gateway = context.injector.get(CredentialGatewayService)
        # Crypto-format coverage uses real CLI stores. Here isolate account verification.
        with (
            patch(
                "api.domains.credential_gateway.sharepoint_broker.sharepoint_refresh_token",
                return_value="planted-grant",
            ),
            patch("api.domains.credential_gateway.sharepoint_broker.httpx.post", return_value=_microsoft_reply()),
            patch(
                "api.domains.credential_gateway.sharepoint_broker.claims_from_id_token",
                return_value={
                    "oid": "other-account",
                    "tid": _content.tenant_id,
                    "aud": _content.client_id,
                    "preferred_username": "someone-else@example.com",
                },
            ),
        ):
            response = context.gateway_client.post(
                "/gateway/v1/sharepoint/handoff",
                headers={"Authorization": f"Bearer {token}"},
                json={"marker": _content.sign_in_id, "store": "fixture", "key": "fixture"},
            )
        assert_that(response.status_code, equal_to(409))
        assert_that(
            context.injector.get(AgentRepository).get_secret(context.agent.id, SecretProvider.SHAREPOINT).content,
            equal_to(secret.content),
        )
        runtime = context.injector.get(IntegrationRepository).runtime(context.agent.id)
        assert runtime is not None
        assert_that(runtime.bindings["sharepoint"]["reconnect_required"], is_(True))
        assert_that(gateway.resolve(f"Bearer {token}").provider, equal_to(SecretProvider.SHAREPOINT))
