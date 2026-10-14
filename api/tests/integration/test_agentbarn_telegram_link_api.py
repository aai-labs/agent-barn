import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from fastapi import status
from hamcrest import (
    assert_that,
    close_to,
    contains_exactly,
    equal_to,
    has_entries,
    is_,
    matches_regexp,
    none,
    not_,
)
from sqlmodel import Session, select
from starlette.testclient import TestClient

from api.domains.communications.agentbarn_telegram_repository import LinkTokenOutcome
from api.domains.communications.agentbarn_telegram_service import AgentBarnTelegramService
from api.domains.communications.models import AgentBarnTelegramLinkToken, CommunicationConnection
from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    TEST_TELEGRAM_BOT_TOKEN,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_agent_access,
    there_is_an_agent,
    there_is_an_agent_in_another_org,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_BOT_ENV = {
    "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
    "LITELLM_BASE_URL": "http://litellm:4000",
    "LITELLM_SECRET_NAME": "litellm",
    "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
    "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
    "SKIP_TELEGRAM_TOKEN_VALIDATION": "true",
    "AGENTBARN_TELEGRAM_BOT_TOKEN": "424242:agentbarn-test-bot-token",
    "AGENTBARN_TELEGRAM_BOT_USERNAME": "AgentBarnTestBot",
}
_TELEGRAM_USER = 5550001


def _given(env: dict[str, str] | None = None) -> list:
    return [
        set_env_variable({**_BOT_ENV, **(env or {})}),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        use_org_for_auth(),
        there_is_an_agent(),
    ]


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _connections(context) -> str:
    return f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections"


def _add(context, payload: dict) -> dict:
    response = context.client.post(_connections(context), json=payload, headers=_auth(context))
    assert response.status_code == status.HTTP_201_CREATED, response.text
    return response.json()


def _add_agentbarn_telegram(context) -> dict:
    return _add(
        context, {"platform_key": "agentbarn_telegram", "display_name": "Agent Barn Telegram", "credentials": {}}
    )


def _tokens(context, connection: dict) -> str:
    return f"{_connections(context)}/{connection['id']}/telegram-link-tokens"


def _links(context, connection: dict) -> str:
    return f"{_connections(context)}/{connection['id']}/telegram-links"


def _raw_token(url: str) -> str:
    return parse_qs(urlparse(url).query)["start"][0]


def _consume(context, raw_token: str, user: int = _TELEGRAM_USER):
    return context.injector.get(AgentBarnTelegramService).consume_link_token(
        raw_token, telegram_user_id=user, telegram_username="jane_doe"
    )


def _stored_tokens(context) -> list[AgentBarnTelegramLinkToken]:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return list(session.exec(select(AgentBarnTelegramLinkToken)))


def test_a_member_gets_a_one_time_telegram_deep_link() -> None:
    with given(_given()) as context:
        client: TestClient = context.client
        connection = _add_agentbarn_telegram(context)

        with when("I ask for a link to connect my Telegram account"):
            response = client.post(_tokens(context, connection), headers=_auth(context))

        with then("I get a deep link to the shared bot that expires in ten minutes"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            url = urlparse(body["url"])
            assert_that((url.scheme, url.netloc, url.path), equal_to(("https", "t.me", "/AgentBarnTestBot")))
            raw = _raw_token(body["url"])
            # Telegram's start parameter allows at most 64 of these characters.
            assert_that(raw, matches_regexp(r"^[A-Za-z0-9_-]{32,64}$"))
            expires_in = datetime.fromisoformat(body["expires_at"]) - datetime.now(UTC)
            assert_that(expires_in.total_seconds(), close_to(600, 5))
            assert_that(body, has_entries(status="waiting", telegram_username=none()))

        with then("only a hash of the token is stored"):
            stored = _stored_tokens(context)
            assert_that(
                [token.token_hash for token in stored], contains_exactly(hashlib.sha256(raw.encode()).hexdigest())
            )
            assert_that(stored[0].token_hash, not_(equal_to(raw)))


def test_a_link_reports_waiting_then_linked_and_the_account_is_listed() -> None:
    with given(_given()) as context:
        client: TestClient = context.client
        connection = _add_agentbarn_telegram(context)
        created = client.post(_tokens(context, connection), headers=_auth(context)).json()
        status_url = f"{_tokens(context, connection)}/{created['id']}"

        with when("I check the link before and after I press Start in Telegram"):
            before = client.get(status_url, headers=_auth(context)).json()
            consumed = _consume(context, _raw_token(created["url"]))
            after = client.get(status_url, headers=_auth(context)).json()
            listed = client.get(_links(context, connection), headers=_auth(context))

        with then("it goes from waiting to linked, and my Telegram account is listed"):
            assert_that(before, has_entries(status="waiting"))
            assert_that(consumed.outcome, equal_to(LinkTokenOutcome.LINKED))
            assert_that(after, has_entries(status="linked", telegram_username="jane_doe"))
            assert_that(listed.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                listed.json(),
                contains_exactly(
                    has_entries(
                        telegram_username="jane_doe",
                        linked_by_membership_id=str(context.organization_user.id),
                    )
                ),
            )


def test_an_unused_link_reports_expired_after_its_deadline() -> None:
    with given(_given()) as context:
        client: TestClient = context.client
        connection = _add_agentbarn_telegram(context)
        created = client.post(_tokens(context, connection), headers=_auth(context)).json()
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            token = session.exec(select(AgentBarnTelegramLinkToken)).one()
            token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.add(token)
            session.commit()

        with when("I check the link after it expired"):
            response = client.get(f"{_tokens(context, connection)}/{created['id']}", headers=_auth(context))

        with then("it reports expired"):
            assert_that(response.json(), has_entries(status="expired"))


def test_unlinking_removes_the_account_once() -> None:
    with given(_given()) as context:
        client: TestClient = context.client
        connection = _add_agentbarn_telegram(context)
        created = client.post(_tokens(context, connection), headers=_auth(context)).json()
        link = _consume(context, _raw_token(created["url"])).link
        assert link is not None

        with when("I unlink the account twice"):
            first = client.delete(f"{_links(context, connection)}/{link.id}", headers=_auth(context))
            again = client.delete(f"{_links(context, connection)}/{link.id}", headers=_auth(context))
            listed = client.get(_links(context, connection), headers=_auth(context)).json()

        with then("it is removed the first time and not found the second"):
            assert_that(first.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            assert_that(again.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(listed, equal_to([]))


def test_a_presented_token_is_matched_by_hash_only() -> None:
    with given(_given()) as context:
        connection = _add_agentbarn_telegram(context)
        context.client.post(_tokens(context, connection), headers=_auth(context))
        stored_hash = _stored_tokens(context)[0].token_hash

        with when("someone presents the stored hash itself instead of the token"):
            result = _consume(context, stored_hash)

        with then("nothing is linked"):
            assert_that(result.outcome, equal_to(LinkTokenOutcome.INVALID))


def test_links_are_only_issued_for_agentbarn_telegram_connections() -> None:
    with given(_given()) as context:
        own = _add(
            context,
            {
                "platform_key": "telegram",
                "display_name": "Telegram",
                "credentials": {"bot_token": TEST_TELEGRAM_BOT_TOKEN},
            },
        )

        with when("I ask for a link on a bring-your-own Telegram Connection"):
            response = context.client.post(_tokens(context, own), headers=_auth(context))

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_a_disabled_connection_issues_no_links() -> None:
    with given(_given()) as context:
        connection = _add_agentbarn_telegram(context)
        context.client.patch(
            f"{_connections(context)}/{connection['id']}",
            json={"revision": connection["revision"], "enabled": False},
            headers=_auth(context),
        )

        with when("I ask for a link while the Connection is turned off"):
            response = context.client.post(_tokens(context, connection), headers=_auth(context))

        with then("it is refused until the Connection is turned back on"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_no_links_are_issued_once_the_shared_bot_is_unconfigured() -> None:
    def existing_connection(context):
        connection = CommunicationConnection(
            organization_id=context.agent.organization_id,
            agent_id=context.agent.id,
            platform_key="agentbarn_telegram",
            display_name="Agent Barn Telegram",
            credentials_encrypted="unused",
        )
        context.injector.get(PostgresRepositoryDelegate).save(connection)
        context.existing = {"id": str(connection.id)}

    unconfigured = {"AGENTBARN_TELEGRAM_BOT_TOKEN": "", "AGENTBARN_TELEGRAM_BOT_USERNAME": ""}
    with given([*_given(unconfigured), existing_connection]) as context:
        with when("I ask for a link"):
            response = context.client.post(_tokens(context, context.existing), headers=_auth(context))

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_linking_requires_agent_update_permission() -> None:
    with given(_given()) as context:
        connection = _add_agentbarn_telegram(context)
        context.organization_user.role = OrganizationRole.MEMBER
        context.injector.get(OrganizationUserRepository).save(context.organization_user)
        there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID)(context)

        with when("a viewer asks for a link and lists the linked accounts"):
            created = context.client.post(_tokens(context, connection), headers=_auth(context))
            listed = context.client.get(_links(context, connection), headers=_auth(context))

        with then("issuing is forbidden but reading linked accounts is allowed"):
            assert_that(created.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(listed.status_code, equal_to(status.HTTP_200_OK))


def test_another_organizations_agent_is_hidden() -> None:
    with given([*_given(), there_is_an_agent_in_another_org()]) as context:
        fake = {"id": "00000000-0000-0000-0000-000000000001"}

        with when("I use the link routes for another Organization's Agent"):
            created = context.client.post(_tokens(context, fake), headers=_auth(context))
            listed = context.client.get(_links(context, fake), headers=_auth(context))

        with then("the Agent is hidden"):
            assert_that(created.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(listed.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_an_unknown_token_status_is_not_found() -> None:
    with given(_given()) as context:
        connection = _add_agentbarn_telegram(context)

        with when("I check a token that does not exist"):
            response = context.client.get(
                f"{_tokens(context, connection)}/00000000-0000-0000-0000-000000000001", headers=_auth(context)
            )

        with then("it is not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(response.json().get("telegram_username"), is_(none()))
