"""The credential gateway reads Gmail for an agent holding only its gateway token.

The app password stays in the database; the agent presents its gateway token and gets
mail back. Every token problem gets the same opaque 403 as the proxy routes.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import status
from hamcrest import assert_that, equal_to
from injector import Module, provider, singleton
from sqlmodel import Session

from api.domains.agents.models import (
    PROVIDER_DISPLAY_NAMES,
    AgentSecret,
    GithubContent,
    GmailAppPasswordContent,
    SecretProvider,
    encrypt_content,
)
from api.domains.agents.repository import AgentRepository
from api.domains.credential_gateway.models import GatewayToken, hash_token, issue_token_value
from api.domains.credential_gateway.repository import GatewayTokenRepository
from api.domains.integrations.repository import IntegrationRepository
from api.infrastructure.google.gmail_imap import (
    GmailInbox,
    InvalidMailQuery,
    MailMessage,
    MailNotFound,
    MailSignInFailed,
    MailSummary,
    MailUnavailable,
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


class FakeInboxModule(Module):
    @provider
    @singleton
    def provide_inbox(self) -> GmailInbox:
        inbox: Any = MagicMock(spec=GmailInbox)
        inbox.list_messages.return_value = [_SUMMARY]
        inbox.get_message.return_value = _MESSAGE
        return inbox


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
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), FakeInboxModule()]),
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


def _inbox(context) -> Any:
    return context.injector.get(GmailInbox)


def test_an_agent_lists_its_inbox_with_only_its_gateway_token():
    with given(_GIVEN) as context:
        _gmail(context)
        token = _token_for(context)

        with when("the agent lists recent mail matching a search"):
            response = context.gateway_client.get(
                "/gateway/v1/mail/messages", params={"q": "from:google", "limit": 5}, headers=_auth(token)
            )

        with then("the gateway signs in with the stored app password and returns the headers"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(
                response.json(),
                equal_to(
                    {"messages": [{"id": "3753", "sender": _SUMMARY.sender, "subject": "Security alert", "date": "d"}]}
                ),
            )
            _inbox(context).list_messages.assert_called_once_with(
                "someone@gmail.com", "abcdefghijklmnop", query="from:google", limit=5
            )


def test_an_agent_reads_one_message():
    with given(_GIVEN) as context:
        _gmail(context)
        token = _token_for(context)

        response = context.gateway_client.get("/gateway/v1/mail/messages/3753", headers=_auth(token))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        body = response.json()
        assert_that(body["body"], equal_to("An app password was created."))
        assert_that(body["attachments"], equal_to(["notice.pdf"]))
        assert_that(body["to"], equal_to("someone@gmail.com"))
        _inbox(context).get_message.assert_called_once_with("someone@gmail.com", "abcdefghijklmnop", "3753")


def test_another_providers_token_cannot_read_mail():
    with given(_GIVEN) as context:
        _gmail(context)
        _secret(context, SecretProvider.GITHUB, GithubContent(token="ghp_x", owner="acme", repos=[], org="acme"))
        github_token = _token_for(context, SecretProvider.GITHUB)

        response = context.gateway_client.get("/gateway/v1/mail/messages", headers=_auth(github_token))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(response.json()["detail"]["error"], equal_to("gateway_token_rejected"))
        _inbox(context).list_messages.assert_not_called()


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer agt_unknown"}, {"Authorization": "Basic Zm9v"}])
def test_a_missing_or_unknown_token_cannot_read_mail(headers):
    with given(_GIVEN) as context:
        _gmail(context)

        response = context.gateway_client.get("/gateway/v1/mail/messages", headers=headers)

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        _inbox(context).list_messages.assert_not_called()


def test_a_mail_token_cannot_use_the_proxy_route():
    with given(_GIVEN) as context:
        _gmail(context)
        token = _token_for(context)

        response = context.gateway_client.get("/gateway/v1/p/gmail_app_password/anything", headers=_auth(token))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


@pytest.mark.parametrize(
    "failure,code,error",
    [
        (MailSignInFailed(), status.HTTP_502_BAD_GATEWAY, "mail_sign_in_failed"),
        (MailUnavailable("down"), status.HTTP_502_BAD_GATEWAY, "upstream_unreachable"),
        (InvalidMailQuery("bad"), status.HTTP_400_BAD_REQUEST, "invalid_query"),
    ],
)
def test_gmail_failures_are_reported_without_detail(failure, code, error):
    with given(_GIVEN) as context:
        _gmail(context)
        token = _token_for(context)
        _inbox(context).list_messages.side_effect = failure

        response = context.gateway_client.get("/gateway/v1/mail/messages", headers=_auth(token))

        assert_that(response.status_code, equal_to(code))
        assert_that(response.json()["detail"]["error"], equal_to(error))
        assert_that("abcdefghijklmnop" in response.text, equal_to(False))


def test_a_missing_message_is_not_found():
    with given(_GIVEN) as context:
        _gmail(context)
        token = _token_for(context)
        _inbox(context).get_message.side_effect = MailNotFound("9")

        response = context.gateway_client.get("/gateway/v1/mail/messages/9", headers=_auth(token))

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


@pytest.mark.parametrize("limit", [0, 51])
def test_the_list_limit_is_bounded(limit):
    with given(_GIVEN) as context:
        _gmail(context)
        token = _token_for(context)

        response = context.gateway_client.get(
            "/gateway/v1/mail/messages", params={"limit": limit}, headers=_auth(token)
        )

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
        _inbox(context).list_messages.assert_not_called()
