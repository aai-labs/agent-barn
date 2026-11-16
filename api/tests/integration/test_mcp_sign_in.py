"""OAuth sign-in and Agent credentials for Organization MCP Servers.

The contract under test:

- saving an OAuth server discovers its authorization server and registers Agent Barn as a
  client, or keeps a client an Admin entered; nothing is probed before a sign-in;
- Owners and Admins sign a server in for the Organization; an Agent's editor signs an Agent
  in with its own account, or gives a token-based server the Agent's own token;
- the sign-in completes only for the person who started it, with permissions rechecked and
  the server's client unchanged;
- reads say which credential each Agent uses and whether someone has to sign in, never the
  credential itself;
- changing a server's URL or sign-in client drops the sign-ins made for the old one.
"""

import json
import urllib.parse
from uuid import UUID, uuid7

import pytest
from fastapi import status
from hamcrest import assert_that, contains_string, empty, equal_to, has_entries, has_length, is_, is_not

from api.domains.events.catalog import AGENT_UPDATED, ORGANIZATION_MCP_SERVER_UPDATED
from api.domains.events.models import OutboxMessage
from api.domains.mcp_servers import oauth
from api.domains.mcp_servers.models import McpServerCredential
from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.integration.test_mcp_servers import FakeProbe, FakeProbeModule
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

URL = "https://mcp.notion.example/mcp"
_SERVERS = "/api/v1/organizations/{organization_id}/mcp-servers"
_METADATA = oauth.OAuthMetadata(
    resource=URL,
    issuer="https://auth.notion.example",
    authorization_endpoint="https://auth.notion.example/authorize",
    token_endpoint="https://auth.notion.example/token",
    registration_endpoint="https://auth.notion.example/register",
    scope="read",
    token_endpoint_auth_methods=["none"],
)


class FakeAuthorizationServer:
    """Stands in for discovery, registration and the token endpoint."""

    def __init__(self) -> None:
        self.registrations = 0
        self.exchanges: list[dict] = []
        self.refused = False

    def install(self, monkeypatch) -> None:
        def register(metadata, redirect_uri):
            self.registrations += 1
            return oauth.OAuthClient(f"client-{self.registrations}", None, "none")

        def exchange(config, *, code, code_verifier, redirect_uri):
            self.exchanges.append({"client_id": config["client_id"], "code": code, "verifier": code_verifier})
            if self.refused:
                raise oauth.OAuthRefused("invalid_grant")
            return oauth.TokenSet("access-1", "refresh-1", 9_999_999_999.0, "read")

        monkeypatch.setattr(oauth, "discover", lambda url: _METADATA)
        monkeypatch.setattr(oauth, "register", register)
        monkeypatch.setattr(oauth, "exchange_code", exchange)


@pytest.fixture
def authorization_server(monkeypatch) -> FakeAuthorizationServer:
    server = FakeAuthorizationServer()
    server.install(monkeypatch)
    return server


def _given(probe: FakeProbe | None = None):
    return [
        set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY, "WEB_APP_URL": "https://app.example.com"}),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), FakeProbeModule(probe or FakeProbe())]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(email="mcp-oauth-owner@example.com"),
        use_org_for_auth(),
        there_is_an_agent(),
    ]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _member(context, role: OrganizationRole = OrganizationRole.MEMBER) -> tuple[str, UUID]:
    saved = {n: getattr(context, n, None) for n in ("user", "organization", "organization_user", "access_token")}
    user_id = uuid7()
    there_is_a_user(id=user_id, email=f"{user_id}@example.com", role=role, organization_id=context.organization.id)(
        context
    )
    membership = context.organization_user.id
    there_is_an_access_token_for_user(user_id)(context)
    token = context.access_token
    for name, value in saved.items():
        setattr(context, name, value)
    return token, membership


def _oauth_server(context, **auth) -> dict:
    response = context.client.post(
        _SERVERS,
        json={"name": "Notion", "url": URL, "scope": "all_agents", "auth": {"type": "oauth", **auth}},
        headers=_auth(context.access_token),
    )
    assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)
    return response.json()


def _token_server(context) -> dict:
    response = context.client.post(
        _SERVERS,
        json={
            "name": "Linear",
            "url": "https://mcp.linear.example/mcp",
            "scope": "all_agents",
            "auth": {"type": "bearer", "token": "org-token"},
        },
        headers=_auth(context.access_token),
    )
    assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)
    return response.json()


def _start(context, server_id: str, *, agent_id: UUID | None = None, token: str | None = None):
    path = (
        f"/api/v1/organizations/{{organization_id}}/agents/{agent_id}/mcp-servers/{server_id}/sign-in"
        if agent_id
        else f"{_SERVERS}/{server_id}/sign-in"
    )
    return context.client.post(path, headers=_auth(token or context.access_token))


def _state(authorize_url: str) -> str:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(authorize_url).query))["state"]


def _complete(context, state: str, *, token: str | None = None):
    return context.client.post(
        f"{_SERVERS}/sign-in/complete",
        json={"code": "the-code", "state": state},
        headers=_auth(token or context.access_token),
    )


def _agent_servers(context, token: str | None = None) -> list[dict]:
    response = context.client.get(
        f"/api/v1/organizations/{{organization_id}}/agents/{context.agent.id}/mcp-servers",
        headers=_auth(token or context.access_token),
    )
    assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
    return response.json()["servers"]


def _credentials(context) -> list[McpServerCredential]:
    return context.injector.get(PostgresRepositoryDelegate).find_all(McpServerCredential)


# --- saving an OAuth server --------------------------------------------------------------


def test_saving_an_oauth_server_registers_agent_barn_and_probes_nothing(authorization_server):
    probe = FakeProbe()
    with given(_given(probe)) as context:
        with when("the Owner saves a server with OAuth sign-in"):
            server = _oauth_server(context)

        with then("Agent Barn registered a client, and nobody is signed in yet"):
            assert_that(authorization_server.registrations, equal_to(1))
            assert_that(
                server,
                has_entries(
                    auth_type="oauth",
                    oauth_client_id="client-1",
                    oauth_registered=True,
                    sign_in=has_entries(status="not_signed_in"),
                ),
            )
            assert_that(probe.calls, empty())


def test_an_entered_client_is_used_instead_of_registering(authorization_server):
    with given(_given()) as context:
        server = _oauth_server(context, client_id="my-app", client_secret="app-secret")

        assert_that(authorization_server.registrations, equal_to(0))
        assert_that(server, has_entries(oauth_client_id="my-app", oauth_registered=False))
        assert_that(json.dumps(server), is_not(contains_string("app-secret")))


def test_renaming_keeps_the_registration_and_the_sign_in(authorization_server):
    with given(_given()) as context:
        server = _oauth_server(context)
        _complete(context, _state(_start(context, server["id"]).json()["authorize_url"]))

        context.client.patch(
            f"{_SERVERS}/{server['id']}", json={"name": "Notion HQ"}, headers=_auth(context.access_token)
        )

        assert_that(authorization_server.registrations, equal_to(1))
        assert_that(_credentials(context), has_length(1))


def test_a_new_url_registers_again_and_drops_the_sign_ins(authorization_server):
    with given(_given()) as context:
        server = _oauth_server(context)
        _complete(context, _state(_start(context, server["id"]).json()["authorize_url"]))

        with when("the Owner points the server at another URL"):
            response = context.client.patch(
                f"{_SERVERS}/{server['id']}",
                json={"url": "https://mcp.notion.example/v2/mcp"},
                headers=_auth(context.access_token),
            )

        with then("a new client is registered and the old sign-in is gone"):
            assert_that(
                response.json(), has_entries(oauth_client_id="client-2", sign_in=has_entries(status="not_signed_in"))
            )
            assert_that(_credentials(context), empty())


def test_an_oauth_server_cannot_be_probed_before_a_sign_in(authorization_server):
    with given(_given()) as context:
        server = _oauth_server(context)

        response = context.client.post(f"{_SERVERS}/{server['id']}/probe", headers=_auth(context.access_token))

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json()["detail"], contains_string("Sign in for the Organization"))


# --- Organization sign-in ----------------------------------------------------------------


def test_an_owner_signs_the_server_in_for_the_organization(authorization_server):
    with given(_given()) as context:
        server = _oauth_server(context)

        with when("the Owner starts a sign-in"):
            started = _start(context, server["id"])

        with then("the authorize URL carries PKCE, the resource and a signed state"):
            assert_that(started.status_code, equal_to(status.HTTP_200_OK), started.text)
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(started.json()["authorize_url"]).query))
            assert_that(
                query,
                has_entries(
                    client_id="client-1",
                    code_challenge_method="S256",
                    resource=URL,
                    redirect_uri="https://app.example.com/api/v1/mcp-servers/oauth/callback",
                ),
            )

        with when("the popup's code comes back"):
            completed = _complete(context, query["state"])

        with then("the Organization is signed in, with the verifier the sign-in started with"):
            assert_that(completed.status_code, equal_to(status.HTTP_200_OK), completed.text)
            assert_that(authorization_server.exchanges[0], has_entries(client_id="client-1", code="the-code"))
            listed = context.client.get(f"{_SERVERS}/{server['id']}", headers=_auth(context.access_token)).json()
            assert_that(listed["sign_in"], has_entries(status="signed_in"))

        with then("the grant is stored encrypted, never in the clear"):
            row = _credentials(context)[0]
            assert_that(row.agent_id, is_(None))
            assert_that(row.credentials_encrypted, is_not(contains_string("refresh-1")))
            assert_that(
                json.loads(decrypt_token(row.credentials_encrypted, TEST_ENCRYPTION_KEY))["refresh_token"],
                equal_to("refresh-1"),
            )

        with then("an update Event records the sign-in"):
            events = [
                m
                for m in context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
                if m.event_name == ORGANIZATION_MCP_SERVER_UPDATED
            ]
            assert_that(events[-1].payload["changed_fields"], equal_to(["sign_in"]))
            assert_that(json.dumps(events[-1].payload), is_not(contains_string("refresh-1")))


def test_a_member_sees_the_sign_in_status_but_cannot_sign_in(authorization_server):
    with given(_given()) as context:
        server = _oauth_server(context)
        member, _ = _member(context)

        listed = context.client.get(_SERVERS, headers=_auth(member)).json()

        assert_that(listed[0]["sign_in"], has_entries(status="not_signed_in"))
        assert_that(_start(context, server["id"], token=member).status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_only_the_person_who_started_a_sign_in_completes_it(authorization_server):
    with given(_given()) as context:
        server = _oauth_server(context)
        state = _state(_start(context, server["id"]).json()["authorize_url"])
        admin, _ = _member(context, OrganizationRole.ADMIN)

        response = _complete(context, state, token=admin)

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(_credentials(context), empty())


def test_a_tampered_state_is_refused(authorization_server):
    with given(_given()) as context:
        server = _oauth_server(context)
        state = _state(_start(context, server["id"]).json()["authorize_url"])

        response = _complete(context, state[:-2] + "xx")

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_a_sign_in_started_before_the_client_changed_is_refused(authorization_server):
    with given(_given()) as context:
        server = _oauth_server(context)
        state = _state(_start(context, server["id"]).json()["authorize_url"])
        context.client.patch(
            f"{_SERVERS}/{server['id']}",
            json={"url": "https://mcp.notion.example/v2/mcp"},
            headers=_auth(context.access_token),
        )

        response = _complete(context, state)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_a_refused_code_saves_nothing(authorization_server):
    with given(_given()) as context:
        server = _oauth_server(context)
        authorization_server.refused = True

        response = _complete(context, _state(_start(context, server["id"]).json()["authorize_url"]))

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(_credentials(context), empty())


def test_signing_out_removes_the_organization_grant(authorization_server):
    with given(_given()) as context:
        server = _oauth_server(context)
        _complete(context, _state(_start(context, server["id"]).json()["authorize_url"]))

        response = context.client.delete(f"{_SERVERS}/{server['id']}/sign-in", headers=_auth(context.access_token))

        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        assert_that(_credentials(context), empty())


def test_the_callback_posts_the_code_to_the_opener_only_with_a_valid_state(authorization_server):
    with given(_given()) as context:
        server = _oauth_server(context)
        state = _state(_start(context, server["id"]).json()["authorize_url"])

        good = context.client.get("/api/v1/mcp-servers/oauth/callback", params={"code": "c1", "state": state})
        bad = context.client.get("/api/v1/mcp-servers/oauth/callback", params={"code": "c1", "state": "forged"})

        assert_that(good.text, contains_string('"code": "c1"'))
        # Also on a channel, for servers whose opener policy severs the popup from the app.
        assert_that(good.text, contains_string('new BroadcastChannel("agentbarn-mcp-sign-in")'))
        assert_that(good.text, contains_string('"https://app.example.com"'))
        assert_that(bad.text, is_not(contains_string('"code"')))


# --- what each Agent uses -----------------------------------------------------------------


def test_an_agent_uses_nothing_until_someone_signs_in(authorization_server):
    with given(_given()) as context:
        _oauth_server(context)

        assert_that(
            _agent_servers(context)[0], has_entries(auth_type="oauth", credential_source="missing", needs_sign_in=True)
        )


def test_an_agent_editor_signs_the_agent_in_with_its_own_account(authorization_server):
    with given(_given()) as context:
        server = _oauth_server(context)
        editor, membership = _member(context)
        there_is_agent_access(membership_id=membership, access_role_id=AGENT_EDITOR_ROLE_ID)(context)

        with when("the Editor signs the Agent in"):
            started = _start(context, server["id"], agent_id=context.agent.id, token=editor)
            completed = _complete(context, _state(started.json()["authorize_url"]), token=editor)

        with then("the Agent uses its own sign-in"):
            assert_that(completed.status_code, equal_to(status.HTTP_200_OK), completed.text)
            assert_that(
                _agent_servers(context, editor)[0],
                has_entries(credential_source="agent", needs_sign_in=False, has_agent_credential=True),
            )

        with then("one agent.updated Event names the switch"):
            events = [
                m
                for m in context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
                if m.event_name == AGENT_UPDATED
            ]
            assert_that(
                events[-1].payload["field_changes"],
                equal_to({"mcp_server_identity.notion": {"previous": "organization", "new": "agent"}}),
            )


def test_an_agent_viewer_cannot_sign_the_agent_in(authorization_server):
    with given(_given()) as context:
        server = _oauth_server(context)
        viewer, membership = _member(context)
        there_is_agent_access(
            membership_id=membership,
            access_role_id=__import__(
                "api.domains.rbac.catalog", fromlist=["AGENT_VIEWER_ROLE_ID"]
            ).AGENT_VIEWER_ROLE_ID,
        )(context)

        assert_that(
            _start(context, server["id"], agent_id=context.agent.id, token=viewer).status_code,
            equal_to(status.HTTP_403_FORBIDDEN),
        )


def test_an_agent_gets_its_own_token_for_a_token_based_server():
    probe = FakeProbe()
    with given(_given(probe)) as context:
        server = _token_server(context)

        with when("the Owner gives the Agent its own token"):
            response = context.client.put(
                f"/api/v1/organizations/{{organization_id}}/agents/{context.agent.id}/mcp-servers/{server['id']}/credential",
                json={
                    "auth": {"type": "api_key", "header_name": "X-Api-Key", "token": "agent-token"},
                    "headers": [
                        {"name": "X-Team", "value": "sales"},
                        {"name": "X-Sig", "value": "sig-1", "secret": True},
                    ],
                },
                headers=_auth(context.access_token),
            )

        with then("it was checked against the server and is now what the Agent uses"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(
                probe.calls[-1][1]["auth"],
                equal_to({"type": "api_key", "header_name": "X-Api-Key", "token": "agent-token"}),
            )
            assert_that(
                response.json()["servers"][0], has_entries(credential_source="agent", has_agent_credential=True)
            )

        with then("its shape reads back for editing, but never its token or secret header"):
            assert_that(
                response.json()["servers"][0]["agent_credential"],
                equal_to(
                    {
                        "auth_type": "api_key",
                        "auth_header_name": "X-Api-Key",
                        "headers": [
                            {"name": "X-Team", "secret": False, "value": "sales"},
                            {"name": "X-Sig", "secret": True, "value": None},
                        ],
                    }
                ),
            )
            assert_that(response.text, is_not(contains_string("agent-token")))
            assert_that(response.text, is_not(contains_string("sig-1")))

        with when("the Owner removes it"):
            removed = context.client.delete(
                f"/api/v1/organizations/{{organization_id}}/agents/{context.agent.id}/mcp-servers/{server['id']}/credential",
                headers=_auth(context.access_token),
            )

        with then("the Agent is back on the Organization's credential"):
            assert_that(removed.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            assert_that(
                _agent_servers(context)[0], has_entries(credential_source="organization", has_agent_credential=False)
            )


def test_an_oauth_server_takes_no_agent_token(authorization_server):
    with given(_given()) as context:
        server = _oauth_server(context)

        response = context.client.put(
            f"/api/v1/organizations/{{organization_id}}/agents/{context.agent.id}/mcp-servers/{server['id']}/credential",
            json={"auth": {"type": "bearer", "token": "agent-token"}},
            headers=_auth(context.access_token),
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
