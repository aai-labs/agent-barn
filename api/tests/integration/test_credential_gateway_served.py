"""The credential gateway answers aai-cli Custom API requests for gateway-served providers.

aai-cli posts the complete request with only the agent's gateway token; the gateway hands
it to the provider's plugin with the decrypted credential and returns ``{status, body}``.
Gmail with an app password is the one such provider: the password stays in the database.
Every token problem gets the same opaque 403 as the proxy routes.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status
from hamcrest import assert_that, equal_to
from sqlmodel import Session, col, select

from api.domains.agents.models import (
    PROVIDER_DISPLAY_NAMES,
    AgentSecret,
    GithubContent,
    GmailAppPasswordContent,
    SecretProvider,
    encrypt_content,
)
from api.domains.agents.repository import AgentRepository
from api.domains.credential_gateway.models import GatewayAuditEvent, GatewayToken, hash_token, issue_token_value
from api.domains.credential_gateway.repository import GatewayTokenRepository
from api.domains.integrations.plugins.providers import GMAIL_SERVED_BASE_URL
from api.domains.integrations.repository import IntegrationRepository
from api.infrastructure.google.gmail_imap import (
    GmailInbox,
    MailMessage,
    MailSignInFailed,
    MailSummary,
)
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

_SUMMARY = MailSummary(id="3753", sender="Google <no-reply@accounts.google.com>", subject="Security alert", date="d")
_MESSAGE = MailMessage(
    id="3753",
    sender=_SUMMARY.sender,
    to="someone@gmail.com",
    cc="",
    subject=_SUMMARY.subject,
    date="d",
    body="An app password was created.",
    truncated=False,
    attachments=["notice.pdf"],
)


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


def _secret(context, provider: SecretProvider, content) -> None:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        session.add(
            AgentSecret(
                agent_id=context.agent.id,
                provider=provider,
                secret_name=PROVIDER_DISPLAY_NAMES[provider],
                content=encrypt_content(content, TEST_ENCRYPTION_KEY),
            )
        )
        session.commit()


def _gmail(context) -> None:
    _secret(
        context,
        SecretProvider.GMAIL_APP_PASSWORD,
        GmailAppPasswordContent(email="someone@gmail.com", app_password="abcd efgh ijkl mnop"),
    )


def _token_for(context, provider: SecretProvider = SecretProvider.GMAIL_APP_PASSWORD) -> str:
    binding = context.injector.get(AgentRepository).get_secret(context.agent.id, provider)
    context.injector.get(IntegrationRepository).set_policy(context.agent.id, provider, True)
    value = issue_token_value()
    context.injector.get(GatewayTokenRepository).save(
        GatewayToken(
            organization_id=context.agent.organization_id,
            agent_id=context.agent.id,
            provider=provider,
            token_hash=hash_token(value),
            binding_id=binding.id if binding else None,
        )
    )
    return value


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


_ROUTE = "/gateway/v1/served/request"


def _request(method: str, path: str, query: dict | None = None, body: Any = None) -> dict:
    """The complete request object aai-cli's isolated Custom API profile posts."""
    return {
        "method": method,
        "url": f"{GMAIL_SERVED_BASE_URL}{path}",
        "query": query or {},
        "body": body,
        "headers": [],
    }


@contextmanager
def _inbox() -> Iterator[Any]:
    inbox: Any = MagicMock(spec=GmailInbox)
    inbox.list_messages.return_value = [_SUMMARY]
    inbox.get_message.return_value = _MESSAGE
    with (
        patch.object(GmailInbox, "list_messages", inbox.list_messages),
        patch.object(GmailInbox, "get_message", inbox.get_message),
    ):
        yield inbox


def test_an_agent_lists_its_inbox_with_only_its_gateway_token():
    with given(_GIVEN) as context, _inbox() as inbox:
        _gmail(context)
        token = _token_for(context)

        with when("aai-cli asks the gateway for recent mail matching a search"):
            response = context.gateway_client.post(
                _ROUTE, json=_request("GET", "/messages", {"q": "from:google", "limit": "5"}), headers=_auth(token)
            )

        with then("the gateway signs in with the stored app password and returns the headers"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(
                response.json(),
                equal_to(
                    {
                        "status": 200,
                        "body": {
                            "messages": [
                                {"id": "3753", "sender": _SUMMARY.sender, "subject": "Security alert", "date": "d"}
                            ]
                        },
                    }
                ),
            )
            inbox.list_messages.assert_called_once_with(
                "someone@gmail.com", "abcdefghijklmnop", query="from:google", limit=5
            )


def test_a_served_request_is_audited_without_the_password():
    with given(_GIVEN) as context, _inbox():
        _gmail(context)
        token = _token_for(context)

        with when("the agent reads its inbox"):
            context.gateway_client.post(_ROUTE, json=_request("GET", "/messages"), headers=_auth(token))

        with then("a durable lifecycle row names the agent and provider"):
            with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
                events = list(
                    session.exec(select(GatewayAuditEvent).where(col(GatewayAuditEvent.kind) == "lifecycle")).all()
                )
            served = [e for e in events if e.detail == "served"]
            assert_that(len(served), equal_to(1))
            assert_that(served[0].provider, equal_to("gmail_app_password"))
            assert_that(served[0].agent_id, equal_to(context.agent.id))
            assert_that("abcdefghijklmnop" in str([e.model_dump() for e in events]), equal_to(False))


def test_an_agent_reads_one_message():
    with given(_GIVEN) as context, _inbox() as inbox:
        _gmail(context)
        token = _token_for(context)

        response = context.gateway_client.post(_ROUTE, json=_request("GET", "/messages/3753"), headers=_auth(token))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        body = response.json()["body"]
        assert_that(body["body"], equal_to("An app password was created."))
        assert_that(body["attachments"], equal_to(["notice.pdf"]))
        assert_that(body["to"], equal_to("someone@gmail.com"))
        inbox.get_message.assert_called_once_with("someone@gmail.com", "abcdefghijklmnop", "3753")


def test_a_write_is_refused_without_contacting_gmail():
    with given(_GIVEN) as context, _inbox() as inbox:
        _gmail(context)
        token = _token_for(context)

        response = context.gateway_client.post(_ROUTE, json=_request("DELETE", "/messages/3753"), headers=_auth(token))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(response.json()["status"], equal_to(405))
        inbox.get_message.assert_not_called()
        inbox.list_messages.assert_not_called()


def test_a_proxied_providers_token_is_refused():
    with given(_GIVEN) as context, _inbox() as inbox:
        _gmail(context)
        _secret(context, SecretProvider.GITHUB, GithubContent(token="ghp_x", owner="acme", repos=[], org="acme"))
        github_token = _token_for(context, SecretProvider.GITHUB)

        response = context.gateway_client.post(_ROUTE, json=_request("GET", "/messages"), headers=_auth(github_token))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(response.json()["detail"]["error"], equal_to("gateway_token_rejected"))
        inbox.list_messages.assert_not_called()


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer agt_unknown"}, {"Authorization": "Basic Zm9v"}])
def test_a_missing_or_unknown_token_is_refused(headers):
    with given(_GIVEN) as context, _inbox() as inbox:
        _gmail(context)

        response = context.gateway_client.post(_ROUTE, json=_request("GET", "/messages"), headers=headers)

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        inbox.list_messages.assert_not_called()


def test_a_served_providers_token_is_not_a_custom_api_connection_credential():
    # Custom API connections own /custom-api/request with their own credentials; a
    # gateway token for a served provider must not reach mail through it.
    with given(_GIVEN) as context, _inbox() as inbox:
        _gmail(context)
        token = _token_for(context)

        response = context.gateway_client.post(
            "/gateway/v1/custom-api/request", json=_request("GET", "/messages"), headers=_auth(token)
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        inbox.list_messages.assert_not_called()


def test_a_served_providers_token_cannot_use_the_proxy_route():
    with given(_GIVEN) as context:
        _gmail(context)
        token = _token_for(context)

        response = context.gateway_client.get("/gateway/v1/p/gmail_app_password/anything", headers=_auth(token))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_gmail_failure_is_reported_in_the_envelope_without_the_password():
    # aai-cli shows the agent nothing from a gateway error status, so a provider failure
    # is returned as the upstream status inside a successful envelope.
    with given(_GIVEN) as context, _inbox() as inbox:
        _gmail(context)
        token = _token_for(context)
        inbox.list_messages.side_effect = MailSignInFailed()

        response = context.gateway_client.post(_ROUTE, json=_request("GET", "/messages"), headers=_auth(token))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["status"], equal_to(502))
        assert_that(response.json()["body"]["error"], equal_to("mail_sign_in_failed"))
        assert_that("abcdefghijklmnop" in response.text, equal_to(False))


@pytest.mark.parametrize(
    "payload",
    [
        {"url": f"{GMAIL_SERVED_BASE_URL}/messages"},
        {"method": "GET"},
        {"method": "GET", "url": "x" * 4097},
        {"method": "G" * 11, "url": f"{GMAIL_SERVED_BASE_URL}/messages"},
    ],
)
def test_a_malformed_request_object_is_rejected(payload):
    with given(_GIVEN) as context, _inbox() as inbox:
        _gmail(context)
        token = _token_for(context)

        response = context.gateway_client.post(_ROUTE, json=payload, headers=_auth(token))

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
        inbox.list_messages.assert_not_called()
