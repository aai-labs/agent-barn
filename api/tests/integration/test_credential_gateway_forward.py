"""End-to-end GATEWAY_PROXY forwarding for GitHub.

Proves the property the whole epic exists for: the agent reaches GitHub with the real
credential applied, and that credential is never in the agent's possession.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import status
from hamcrest import assert_that, equal_to, is_, is_not
from injector import Module, provider, singleton
from starlette.testclient import TestClient

from api.domains.agents.models import (
    PROVIDER_DISPLAY_NAMES,
    AgentSecret,
    BitbucketContent,
    ConfluenceContent,
    GithubContent,
    JiraContent,
    PipedriveContent,
    SecretProvider,
    encrypt_content,
)
from api.domains.credential_gateway.forwarding import UpstreamForwarder, UpstreamResponse
from api.domains.credential_gateway.models import GatewayToken, hash_token, issue_token_value
from api.domains.credential_gateway.repository import GatewayTokenRepository
from api.domains.credential_gateway.service import CredentialGatewayService
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
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

REAL_TOKEN = "ghp_the_real_secret"


class RecordingForwarderModule(Module):
    """Captures the outbound request instead of calling GitHub."""

    @provider
    @singleton
    def provide_forwarder(self) -> UpstreamForwarder:
        mock: Any = MagicMock(spec=UpstreamForwarder)
        mock.send.return_value = UpstreamResponse(
            status_code=200, content=b'{"number": 7}', headers={"Content-Type": "application/json"}
        )
        return mock


_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "CREDENTIAL_GATEWAY_ENABLED": "true",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), RecordingForwarderModule()]),
    prepare_api_server(),
    create_test_client(),
    prepare_gateway_server(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(),
]


def _github_secret(context) -> None:
    _provider_secret(
        context,
        SecretProvider.GITHUB,
        GithubContent(token=REAL_TOKEN, owner="acme", repos=["r1"], org="acme-org"),
    )


def _provider_secret(context, provider: SecretProvider, content) -> None:
    from sqlmodel import Session

    delegate = context.injector.get(PostgresRepositoryDelegate)
    with Session(delegate.engine) as session:
        session.add(
            AgentSecret(
                agent_id=context.agent.id,
                provider=provider,
                secret_name=PROVIDER_DISPLAY_NAMES[provider],
                content=encrypt_content(content, TEST_ENCRYPTION_KEY),
            )
        )
        session.commit()


def _token_for(context, provider: SecretProvider = SecretProvider.GITHUB) -> str:
    value = issue_token_value()
    context.injector.get(GatewayTokenRepository).save(
        GatewayToken(
            organization_id=context.agent.organization_id,
            agent_id=context.agent.id,
            provider=provider,
            token_hash=hash_token(value),
        )
    )
    return value


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _sent(context):
    return context.injector.get(UpstreamForwarder).send.call_args


# --- the property the epic exists for ---


def test_the_agent_reaches_github_without_ever_holding_the_credential():
    with given(_GIVEN) as context:
        gateway: TestClient = context.gateway_client
        _github_secret(context)
        token = _token_for(context)

        with when("the agent calls GitHub through the gateway"):
            response = gateway.get(
                "/gateway/v1/p/github/repos/acme/r1/pulls/7",
                headers={**_auth(token), "Accept": "*/*"},
            )

        with then("the response comes back and the real token was applied upstream"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json(), equal_to({"number": 7}))
            call = _sent(context)
            assert_that(call.args[0], equal_to("GET"))
            assert_that(call.args[1], equal_to("https://api.github.com/repos/acme/r1/pulls/7"))
            assert_that(call.kwargs["headers"]["Authorization"], equal_to(f"Bearer {REAL_TOKEN}"))

        with then("the agent's own gateway token never went upstream"):
            assert_that(token in str(_sent(context).kwargs["headers"]), is_(False))


_ALL_AAI_GIVEN = [step for step in _GIVEN]
_ALL_AAI_GIVEN[0] = set_env_variable(
    {
        "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
        "LITELLM_BASE_URL": "http://litellm:4000",
        "LITELLM_SECRET_NAME": "litellm",
        "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
        "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        "CREDENTIAL_GATEWAY_ENABLED": "true",
    }
)


@pytest.mark.parametrize(
    ("provider", "content", "path", "expected_url", "auth_header", "auth_value"),
    [
        (
            SecretProvider.JIRA,
            JiraContent(site_url="https://acme.atlassian.net", email="jira@example.com", api_token="jira-real"),
            "rest/api/3/issue/AF-1",
            "https://acme.atlassian.net/rest/api/3/issue/AF-1",
            "Authorization",
            "Basic amlyYUBleGFtcGxlLmNvbTpqaXJhLXJlYWw=",
        ),
        (
            SecretProvider.CONFLUENCE,
            ConfluenceContent(site_url="https://acme.atlassian.net", email="conf@example.com", api_token="conf-real"),
            "wiki/api/v2/spaces",
            "https://acme.atlassian.net/wiki/api/v2/spaces",
            "Authorization",
            "Basic Y29uZkBleGFtcGxlLmNvbTpjb25mLXJlYWw=",
        ),
        (
            SecretProvider.BITBUCKET,
            BitbucketContent(workspace="acme", repos=["app"], email="bb@example.com", api_token="bb-real"),
            "repositories/acme/app/pullrequests",
            "https://api.bitbucket.org/2.0/repositories/acme/app/pullrequests",
            "Authorization",
            "Basic YmJAZXhhbXBsZS5jb206YmItcmVhbA==",
        ),
        (
            SecretProvider.PIPEDRIVE,
            PipedriveContent(api_token="pd-real", domain="acme"),
            "v1/deals",
            "https://acme.pipedrive.com/v1/deals",
            "x-api-token",
            "pd-real",
        ),
    ],
)
def test_each_non_oauth_aai_provider_is_reauthorized_and_forwarded(
    provider, content, path, expected_url, auth_header, auth_value
):
    with given(_ALL_AAI_GIVEN) as context:
        _provider_secret(context, provider, content)
        token = _token_for(context, provider)

        response = context.gateway_client.get(f"/gateway/v1/p/{provider.value}/{path}", headers=_auth(token))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        call = _sent(context)
        assert_that(call.args[1], equal_to(expected_url))
        assert_that(call.kwargs["headers"][auth_header], equal_to(auth_value))
        assert_that(token in str(call.kwargs["headers"]), is_(False))


def test_query_parameters_survive_the_hop():
    with given(_GIVEN) as context:
        _github_secret(context)
        token = _token_for(context)

        with when("the agent passes a query string"):
            context.gateway_client.get(
                "/gateway/v1/p/github/repos/acme/r1/pulls?state=open&per_page=5",
                headers=_auth(token),
            )

        with then("it reaches the provider unchanged"):
            assert_that(_sent(context).kwargs["params"], equal_to({"state": "open", "per_page": "5"}))


def test_a_request_body_survives_the_hop():
    with given(_GIVEN) as context:
        _github_secret(context)
        token = _token_for(context)

        with when("the agent posts a review comment"):
            context.gateway_client.post(
                "/gateway/v1/p/github/repos/acme/r1/issues/7/comments",
                headers=_auth(token),
                json={"body": "looks good"},
            )

        with then("the body is forwarded verbatim"):
            assert_that(b"looks good" in _sent(context).kwargs["content"], is_(True))


def test_an_upstream_error_status_reaches_the_agent_unchanged():
    with given(_GIVEN) as context:
        _github_secret(context)
        token = _token_for(context)
        context.injector.get(UpstreamForwarder).send.return_value = UpstreamResponse(
            status_code=404, content=b'{"message":"Not Found"}', headers={}
        )

        with when("GitHub returns 404"):
            response = context.gateway_client.get("/gateway/v1/p/github/repos/acme/nope", headers=_auth(token))

        with then("the agent sees GitHub's answer, not a gateway error"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


# --- refusals ---


def test_revoking_the_credential_stops_the_next_request():
    with given(_GIVEN) as context:
        gateway: TestClient = context.gateway_client
        _github_secret(context)
        token = _token_for(context)
        assert gateway.get("/gateway/v1/p/github/user", headers=_auth(token)).status_code == status.HTTP_200_OK

        with when("the Agent's tokens are revoked mid-session"):
            context.injector.get(CredentialGatewayService).revoke_for_agent(
                context.agent.id, context.agent.organization_id
            )

        with then("the very next request is refused"):
            refused = gateway.get("/gateway/v1/p/github/user", headers=_auth(token))
            assert_that(refused.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_token_cannot_be_used_against_another_providers_path():
    # A Jira token reaching /p/github must not resolve into a GitHub credential.
    with given(_GIVEN) as context:
        _github_secret(context)
        jira_token = _token_for(context, SecretProvider.JIRA)

        with when("a Jira token is presented on the GitHub path"):
            response = context.gateway_client.get("/gateway/v1/p/github/user", headers=_auth(jira_token))

        with then("it is refused and nothing is forwarded"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(context.injector.get(UpstreamForwarder).send.called, is_(False))


def test_an_agent_with_no_credential_for_the_provider_is_refused():
    with given(_GIVEN) as context:
        token = _token_for(context)  # no AgentSecret seeded

        with when("the agent calls through the gateway"):
            response = context.gateway_client.get("/gateway/v1/p/github/user", headers=_auth(token))

        with then("it is refused rather than forwarded unauthenticated"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(context.injector.get(UpstreamForwarder).send.called, is_(False))


def test_the_refusal_shape_matches_the_identity_endpoint():
    with given(_GIVEN) as context:
        with when("an unknown token is presented to both endpoints"):
            unknown = issue_token_value()
            identity = context.gateway_client.get("/gateway/v1/identity", headers=_auth(unknown))
            forward = context.gateway_client.get("/gateway/v1/p/github/user", headers=_auth(unknown))

        with then("an agent cannot tell the failure modes apart"):
            assert_that(forward.status_code, equal_to(identity.status_code))
            assert_that(forward.json(), equal_to(identity.json()))


# --- rollback ---


_ROLLED_BACK = [step for step in _GIVEN]
_ROLLED_BACK[0] = set_env_variable(
    {
        "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
        "LITELLM_BASE_URL": "http://litellm:4000",
        "LITELLM_SECRET_NAME": "litellm",
        "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
        "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        "CREDENTIAL_GATEWAY_ENABLED": "false",
    }
)


def test_rolling_a_provider_back_refuses_its_live_tokens():
    # Rollback is one config change, so tokens issued before it are still in pods. They
    # must stop working: the pod now holds the real credential again, and forwarding
    # must not remain an unaudited second path to the credential.
    with given(_ROLLED_BACK) as context:
        _github_secret(context)
        token = _token_for(context)

        with when("GitHub is no longer routed through the gateway"):
            response = context.gateway_client.get("/gateway/v1/p/github/user", headers=_auth(token))

        with then("the live token is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(context.injector.get(UpstreamForwarder).send.called, is_(False))


def test_issuance_follows_plugin_modes_when_the_gateway_is_enabled():
    with given(_GIVEN) as context:
        service = context.injector.get(CredentialGatewayService)

        with when("start issues tokens with GitHub enabled"):
            issued = service.issue_for_agent(
                context.agent.id,
                context.agent.organization_id,
                {SecretProvider.GITHUB, SecretProvider.JIRA},
            )

        with then("every gateway-proxy plugin gets one without a provider allowlist"):
            assert_that(
                [i.provider for i in issued],
                equal_to([SecretProvider.GITHUB, SecretProvider.JIRA]),
            )
            assert_that(issued[0].value, is_not(equal_to("")))
