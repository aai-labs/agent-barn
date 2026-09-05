"""Gateway Token issue / resolve / revoke round-trip against the real gateway app."""

import base64

from fastapi import status
from hamcrest import assert_that, equal_to, is_, not_none
from sqlmodel import Session, col, select
from starlette.testclient import TestClient

from api.domains.agents.models import SecretProvider
from api.domains.credential_gateway.models import (
    TOKEN_PREFIX,
    GatewayAuditEvent,
    gateway_token_env_var,
    hash_token,
    issue_token_value,
)
from api.domains.credential_gateway.service import CredentialGatewayService
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
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)

_IDENTITY = "/gateway/v1/identity"

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


def _issue(context, agent, provider=SecretProvider.GITHUB):
    """Issue a token directly through the repository.

    Bypasses ``issue_for_agent``'s egress-mode policy deliberately, so the gateway's
    identity contract is testable independently of which providers it currently serves.
    """
    from api.domains.credential_gateway.models import GatewayToken
    from api.domains.credential_gateway.repository import GatewayTokenRepository

    value = issue_token_value()
    repo = context.injector.get(GatewayTokenRepository)
    repo.save(
        GatewayToken(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            provider=provider,
            token_hash=hash_token(value),
        )
    )
    return value


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- resolution ---


def test_a_live_token_resolves_to_its_agent_organization_and_provider():
    with given(_GIVEN) as context:
        gateway: TestClient = context.gateway_client
        agent = context.agent
        token = _issue(context, agent)

        with when("the agent presents its gateway token"):
            response = gateway.get(_IDENTITY, headers=_auth(token))

        with then("the gateway identifies it without returning credential material"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["agent_id"], equal_to(str(agent.id)))
            assert_that(body["organization_id"], equal_to(str(agent.organization_id)))
            assert_that(body["provider"], equal_to("github"))
            assert_that(set(body), equal_to({"agent_id", "organization_id", "provider"}))


def test_a_basic_auth_transport_can_present_the_token_as_its_password():
    with given(_GIVEN) as context:
        token = _issue(context, context.agent)
        encoded = base64.b64encode(f"calendar-user:{token}".encode()).decode()

        response = context.gateway_client.get(_IDENTITY, headers={"Authorization": f"Basic {encoded}"})

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["provider"], equal_to("github"))


def test_a_revoked_token_stops_resolving():
    with given(_GIVEN) as context:
        gateway: TestClient = context.gateway_client
        agent = context.agent
        token = _issue(context, agent)
        assert gateway.get(_IDENTITY, headers=_auth(token)).status_code == status.HTTP_200_OK

        with when("the token is revoked"):
            context.injector.get(CredentialGatewayService).revoke_for_agent(agent.id, agent.organization_id)

        with then("the very next request is refused"):
            response = gateway.get(_IDENTITY, headers=_auth(token))
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_an_unknown_token_is_refused():
    with given(_GIVEN) as context:
        with when("a well-formed but unissued token is presented"):
            response = context.gateway_client.get(_IDENTITY, headers=_auth(issue_token_value()))

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_refusal_is_structured_and_does_not_distinguish_unknown_from_revoked():
    # An agent must not be able to probe which of its tokens were withdrawn; the
    # distinction lives in the audit trail, not the response.
    with given(_GIVEN) as context:
        gateway: TestClient = context.gateway_client
        agent = context.agent
        revoked = _issue(context, agent)
        context.injector.get(CredentialGatewayService).revoke_for_agent(agent.id, agent.organization_id)

        with when("an unknown and a revoked token are both presented"):
            unknown_response = gateway.get(_IDENTITY, headers=_auth(issue_token_value()))
            revoked_response = gateway.get(_IDENTITY, headers=_auth(revoked))

        with then("both give the same structured 403"):
            assert_that(unknown_response.json(), equal_to(revoked_response.json()))
            detail = unknown_response.json()["detail"]
            assert_that(detail["error"], equal_to("gateway_token_rejected"))
            assert_that(detail["message"], is_(not_none()))


def test_a_missing_authorization_header_is_refused():
    with given(_GIVEN) as context:
        with when("no credential is presented"):
            response = context.gateway_client.get(_IDENTITY)

        with then("it is refused rather than treated as anonymous"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_credential_for_another_service_is_refused():
    # A LiteLLM or Communications key reaching this endpoint must never be hashed and
    # looked up; the prefix check rejects it first.
    with given(_GIVEN) as context:
        with when("a non-gateway bearer credential is presented"):
            response = context.gateway_client.get(_IDENTITY, headers=_auth("sk-not-a-gateway-token"))

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


# --- issuance ---
#
# `issue_for_agent` skips any provider whose plugin is EgressMode.DIRECT (see
# providers_needing_a_token). There is no such provider left in the shipped catalogue to
# demonstrate that against — every plugin now has a gateway-served mode — so the
# behavior is covered only by test_integration_plugins.py's registry contract tests.


def test_reissuing_revokes_the_previous_token():
    with given(_GIVEN) as context:
        gateway: TestClient = context.gateway_client
        agent = context.agent
        first = _issue(context, agent)

        with when("the agent restarts and issuance runs again"):
            context.injector.get(CredentialGatewayService).issue_for_agent(
                agent.id, agent.organization_id, {SecretProvider.GITHUB}
            )

        with then("the token from the previous start no longer resolves"):
            assert_that(
                gateway.get(_IDENTITY, headers=_auth(first)).status_code,
                equal_to(status.HTTP_403_FORBIDDEN),
            )


def test_revoking_one_provider_leaves_the_others_working():
    with given(_GIVEN) as context:
        gateway: TestClient = context.gateway_client
        agent = context.agent
        github = _issue(context, agent, SecretProvider.GITHUB)
        jira = _issue(context, agent, SecretProvider.JIRA)

        with when("only the GitHub Integration's credential is removed"):
            context.injector.get(CredentialGatewayService).revoke_for_agent(
                agent.id, agent.organization_id, providers={SecretProvider.GITHUB}
            )

        with then("Jira keeps working"):
            assert_that(
                gateway.get(_IDENTITY, headers=_auth(github)).status_code,
                equal_to(status.HTTP_403_FORBIDDEN),
            )
            assert_that(
                gateway.get(_IDENTITY, headers=_auth(jira)).status_code,
                equal_to(status.HTTP_200_OK),
            )


# --- token shape ---


def test_a_token_is_prefixed_and_stored_only_as_a_hash():
    with given(_GIVEN) as context:
        agent = context.agent
        value = _issue(context, agent)

        with then("the plaintext never reaches the database"):
            from api.domains.credential_gateway.repository import GatewayTokenRepository

            stored = context.injector.get(GatewayTokenRepository).find_active_by_hash(hash_token(value))
            assert_that(value.startswith(TOKEN_PREFIX), is_(True))
            assert_that(stored, is_(not_none()))
            assert_that(stored.token_hash, equal_to(hash_token(value)))
            assert_that(stored.token_hash == value, is_(False))


def test_the_pod_env_var_is_scoped_per_provider():
    # One variable per provider, so revoking one Integration cannot take the others down.
    assert_that(gateway_token_env_var(SecretProvider.GITHUB), equal_to("AF_GATEWAY_TOKEN_GITHUB"))
    assert_that(
        gateway_token_env_var(SecretProvider.GOOGLE_WORKSPACE),
        equal_to("AF_GATEWAY_TOKEN_GOOGLE_WORKSPACE"),
    )


# --- durable audit trail ---
#
# The row rides the same Postgres the resolution/issuance hot paths already depend on,
# so there is no separate ingest step to lose it to.


def _audit_events(context, kind: str) -> list[GatewayAuditEvent]:
    with Session(context.postgres_delegate.engine) as session:
        query = select(GatewayAuditEvent).where(col(GatewayAuditEvent.kind) == kind)
        return list(session.exec(query).all())


def test_a_successful_resolution_persists_a_durable_row():
    with given(_GIVEN) as context:
        agent = context.agent
        token = _issue(context, agent)

        with when("the agent presents its gateway token"):
            context.gateway_client.get(_IDENTITY, headers=_auth(token))

        with then("a durable resolution row is written, not just the log and counter"):
            events = _audit_events(context, "resolution")
            assert_that(len(events), equal_to(1))
            assert_that(events[0].detail, equal_to("resolved"))
            assert_that(events[0].provider, equal_to("github"))
            assert_that(events[0].agent_id, equal_to(agent.id))
            assert_that(events[0].organization_id, equal_to(agent.organization_id))


def test_an_unknown_token_persists_a_row_with_no_identity():
    with given(_GIVEN) as context:
        with when("a well-formed but unissued token is presented"):
            context.gateway_client.get(_IDENTITY, headers=_auth(issue_token_value()))

        with then("the row records the outcome without an agent or provider to name"):
            events = _audit_events(context, "resolution")
            assert_that(len(events), equal_to(1))
            assert_that(events[0].detail, equal_to("unknown"))
            assert_that(events[0].provider, is_(None))
            assert_that(events[0].agent_id, is_(None))


def test_issuing_and_revoking_persist_durable_lifecycle_rows():
    with given(_GIVEN) as context:
        agent = context.agent
        service = context.injector.get(CredentialGatewayService)

        with when("a token is issued and then revoked"):
            service.issue_for_agent(agent.id, agent.organization_id, {SecretProvider.GITHUB})
            service.revoke_for_agent(agent.id, agent.organization_id)

        with then("both lifecycle transitions are durably recorded"):
            events = {e.detail for e in _audit_events(context, "lifecycle")}
            assert_that(events, equal_to({"issued", "revoked"}))
