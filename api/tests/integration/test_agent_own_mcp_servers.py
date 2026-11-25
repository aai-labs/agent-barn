"""Agent MCP Servers and restricted Organization MCP Servers.

The contract under test:

- an Agent MCP Server belongs to one Agent: its Owners and Editors add, change and remove it
  (`agent.update` and `agent.secret.manage`), it is checked against the live server like an
  Organization server, it reaches only that Agent's runtime, and it is never reachable
  through the Organization routes or another Agent's;
- its identifier cannot meet an Organization server's in the Agent's runtime, either way;
- they are seen through their Agent only, never listed on the Organization, and no
  Organization switch turns them off;
- a restricted Organization server can be switched on or off for an Agent, or given an
  Agent's own credential, only by an Organization Owner or Admin.
"""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import status
from hamcrest import (
    assert_that,
    contains_exactly,
    contains_string,
    empty,
    equal_to,
    has_entries,
    has_key,
    is_,
    is_not,
    none,
)

from api.domains.events.catalog import (
    ORGANIZATION_MCP_SERVER_CREATED,
    ORGANIZATION_MCP_SERVER_UPDATED,
)
from api.domains.events.models import OutboxMessage
from api.domains.mcp_servers.models import McpServerScope, OrganizationMcpServer
from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID, AGENT_VIEWER_ROLE_ID
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector
from api.tests.integration.test_agent_mcp_servers import _ENV, _member
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

_TOKEN = "agent-server-token"


def _given(probe: FakeProbe | None = None):
    return [
        _ENV,
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), FakeProbeModule(probe or FakeProbe())]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(email="mcp-own-owner@example.com"),
        use_org_for_auth(),
        there_is_an_agent(),
    ]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _agent_path(context, agent_id: UUID | None = None) -> str:
    return f"/api/v1/organizations/{context.organization.id}/agents/{agent_id or context.agent.id}/mcp-servers"


def _org_path(context) -> str:
    return f"/api/v1/organizations/{context.organization.id}/mcp-servers"


def _body(**overrides: Any) -> dict:
    return {
        "name": "Linear",
        "url": "https://mcp.linear.app/mcp",
        "auth": {"type": "bearer", "token": _TOKEN},
        **overrides,
    }


def _add(context, token: str | None = None, agent_id: UUID | None = None, **overrides: Any):
    return context.client.post(
        _agent_path(context, agent_id), json=_body(**overrides), headers=_auth(token or context.access_token)
    )


def _added(context, **overrides: Any) -> dict:
    response = _add(context, **overrides)
    assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)
    return response.json()


def _editor(context, role_id: UUID = AGENT_EDITOR_ROLE_ID) -> str:
    token, membership = _member(context)
    there_is_agent_access(membership_id=membership, access_role_id=role_id)(context)
    return token


def _admin(context) -> str:
    token, _ = _member(context, OrganizationRole.ADMIN)
    return token


def _org_server(context, identifier: str, **fields) -> OrganizationMcpServer:
    config = fields.pop("config", {"auth": {"type": "bearer", "token": "org-token"}, "headers": []})
    server = OrganizationMcpServer(
        organization_id=context.organization.id,
        identifier=identifier,
        name=identifier.title(),
        url=f"https://{identifier}.example.com/mcp",
        scope=fields.pop("scope", McpServerScope.SELECTED_AGENTS.value),
        credentials_encrypted=encrypt_token(json.dumps(config), TEST_ENCRYPTION_KEY),
        **fields,
    )
    context.injector.get(PostgresRepositoryDelegate).save(server)
    return server


def _events(context, name: str) -> list[OutboxMessage]:
    return [m for m in context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage) if m.event_name == name]


def _start(context) -> dict:
    response = context.client.post(
        f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/start",
        headers=_auth(context.access_token),
    )
    assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
    return context.injector.get(KubernetesClient).create_config_map.call_args.args[1].data


# --- Agent servers ----------------------------------------------------------------


def test_an_agent_editor_adds_a_server_for_their_agent_only():
    probe = FakeProbe()
    with given(_given(probe)) as context:
        token = _editor(context)

        with when("an Agent Editor adds a server to the Agent"):
            response = _add(context, token=token)

        with then("it is checked against the live server and saved for that Agent"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)
            assert_that(
                response.json(),
                has_entries(identifier="linear", scope="agent", agent_id=str(context.agent.id), restricted=False),
            )
            assert_that(probe.calls[0][1]["auth"], has_entries(type="bearer", token=_TOKEN))

        with then("the Agent lists it as its own, and the Organization list does not have it"):
            read = context.client.get(_agent_path(context), headers=_auth(token)).json()
            assert_that([s["identifier"] for s in read["agent_servers"]], contains_exactly("linear"))
            assert_that(read["servers"], empty())
            organization = context.client.get(_org_path(context), headers=_auth(context.access_token)).json()
            assert_that(organization, empty())

        with then("its created Event is about the Agent and carries no credential"):
            event = _events(context, ORGANIZATION_MCP_SERVER_CREATED)[-1]
            assert_that(event.subject, has_entries(type="AGENT", id=str(context.agent.id)))
            assert_that(event.payload, has_entries(agent_id=str(context.agent.id), scope="agent"))
            assert_that(json.dumps(event.payload), is_not(contains_string(_TOKEN)))


def test_an_agent_server_reaches_only_its_agents_runtime():
    with given(_given()) as context:
        _added(context)
        mine = context.agent
        there_is_an_agent(name="Other Agent")(context)
        other = context.agent

        with when("both Agents start"):
            context.agent = other
            others_config = _start(context)
            context.agent = mine
            my_config = _start(context)

        with then("only the Agent the server belongs to lists it, through the gateway"):
            my_servers = json.loads(my_config["openclaw-config-overlay.json"])["mcp"]["servers"]
            assert_that(my_servers, has_key("linear"))
            assert_that(my_servers["linear"]["url"], contains_string("/gateway/v1/mcp/linear"))
            assert_that(json.dumps(my_config), is_not(contains_string(_TOKEN)))
            assert_that(json.loads(others_config["openclaw-config-overlay.json"])["mcp"]["servers"], equal_to({}))


def test_a_viewer_sees_the_agents_servers_without_their_url_and_cannot_add_one():
    with given(_given()) as context:
        _added(context)
        token = _editor(context, AGENT_VIEWER_ROLE_ID)

        read = context.client.get(_agent_path(context), headers=_auth(token)).json()

        assert_that(read["agent_servers"][0], has_entries(name="Linear", url=none(), auth_type=none()))
        assert_that(_add(context, token=token, name="Other").status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_an_agent_server_is_out_of_reach_of_the_organization_routes_and_other_agents():
    with given(_given()) as context:
        server_id = _added(context)["id"]
        mine = context.agent
        there_is_an_agent(name="Other Agent")(context)
        other = context.agent
        context.agent = mine
        auth = _auth(context.access_token)

        with then("the Organization routes do not find it"):
            assert_that(
                context.client.get(f"{_org_path(context)}/{server_id}", headers=auth).status_code,
                equal_to(status.HTTP_404_NOT_FOUND),
            )
            assert_that(
                context.client.patch(f"{_org_path(context)}/{server_id}", json={"name": "X"}, headers=auth).status_code,
                equal_to(status.HTTP_404_NOT_FOUND),
            )
            assert_that(
                context.client.post(f"{_org_path(context)}/{server_id}/sign-in", headers=auth).status_code,
                equal_to(status.HTTP_404_NOT_FOUND),
            )

        with then("another Agent's routes do not find it"):
            assert_that(
                context.client.patch(
                    f"{_agent_path(context, other.id)}/{server_id}", json={"name": "X"}, headers=auth
                ).status_code,
                equal_to(status.HTTP_404_NOT_FOUND),
            )
            assert_that(
                context.client.put(
                    f"{_agent_path(context, other.id)}/{server_id}/credential",
                    json={"auth": {"type": "bearer", "token": "t"}},
                    headers=auth,
                ).status_code,
                equal_to(status.HTTP_404_NOT_FOUND),
            )

        with then("its own Agent's routes change and remove it"):
            renamed = context.client.patch(
                f"{_agent_path(context)}/{server_id}", json={"name": "Renamed"}, headers=auth
            )
            assert_that(renamed.json(), has_entries(name="Renamed", identifier="linear"))
            removed = context.client.delete(f"{_agent_path(context)}/{server_id}", headers=auth)
            assert_that(removed.status_code, equal_to(status.HTTP_204_NO_CONTENT))


def test_agent_and_organization_identifiers_never_meet():
    with given(_given()) as context:
        _org_server(context, "linear")

        with then("an Agent server cannot take an Organization server's identifier"):
            refused = _add(context)
            assert_that(refused.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(refused.json()["detail"], contains_string("an Organization MCP server"))

        with then("nor can an Organization server take an Agent server's"):
            _added(context, name="Notion")
            response = context.client.post(
                _org_path(context),
                json={**_body(name="Notion"), "scope": "all_agents"},
                headers=_auth(context.access_token),
            )
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(response.json()["detail"], contains_string("an Agent's own MCP server"))

        with then("two Agents may each have a server of the same name"):
            there_is_an_agent(name="Other Agent")(context)
            assert_that(_add(context, name="Notion").status_code, equal_to(status.HTTP_201_CREATED))


def test_a_deleted_agents_server_does_not_hold_its_identifier():
    with given(_given()) as context:
        _added(context, name="Notion")
        context.agent.deleted_at = datetime.now(UTC)
        context.injector.get(PostgresRepositoryDelegate).save(context.agent)

        response = context.client.post(
            _org_path(context),
            json={**_body(name="Notion"), "scope": "all_agents"},
            headers=_auth(context.access_token),
        )

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)


def test_no_route_lists_every_agents_servers():
    with given(_given()) as context:
        _added(context)

        listed = context.client.get(f"{_org_path(context)}/agent-servers", headers=_auth(context.access_token))
        organization = context.client.get(_org_path(context), headers=_auth(context.access_token)).json()

        # An Agent's own servers are seen through that Agent, like its own integration credentials.
        assert_that(listed.status_code, is_not(equal_to(status.HTTP_200_OK)))
        assert_that(organization, empty())


# --- restricted Organization servers ------------------------------------------------


def _attach(context, *servers: OrganizationMcpServer, token: str):
    return context.client.put(
        _agent_path(context), json={"attached_server_ids": [str(s.id) for s in servers]}, headers=_auth(token)
    )


def test_a_restricted_server_is_attached_by_owners_and_admins_only():
    with given(_given()) as context:
        restricted = _org_server(context, "payroll", restricted=True)
        open_server = _org_server(context, "wiki")
        editor = _editor(context)

        with then("an Editor attaches an open server but not a restricted one"):
            assert_that(_attach(context, open_server, token=editor).status_code, equal_to(status.HTTP_200_OK))
            refused = _attach(context, open_server, restricted, token=editor)
            assert_that(refused.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(refused.json()["detail"], contains_string("restricted"))

        with then("an Admin attaches the restricted one"):
            allowed = _attach(context, open_server, restricted, token=_admin(context))
            assert_that(allowed.status_code, equal_to(status.HTTP_200_OK), allowed.text)

        with then("the Editor still saves other changes while leaving it attached, but cannot remove it"):
            read = context.client.get(_agent_path(context), headers=_auth(editor)).json()
            assert_that(read["can_manage_restricted"], is_(False))
            assert_that(_attach(context, restricted, token=editor).status_code, equal_to(status.HTTP_200_OK))
            assert_that(_attach(context, token=editor).status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_restricted_server_takes_an_agent_credential_from_owners_and_admins_only():
    with given(_given()) as context:
        restricted = _org_server(context, "payroll", restricted=True, scope=McpServerScope.ALL_AGENTS.value)
        editor = _editor(context)
        path = f"{_agent_path(context)}/{restricted.id}/credential"
        credential = {"auth": {"type": "bearer", "token": "agent-token"}}

        assert_that(
            context.client.put(path, json=credential, headers=_auth(editor)).status_code,
            equal_to(status.HTTP_403_FORBIDDEN),
        )
        assert_that(context.client.delete(path, headers=_auth(editor)).status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(
            context.client.put(path, json=credential, headers=_auth(context.access_token)).status_code,
            equal_to(status.HTTP_200_OK),
        )


def test_a_restricted_oauth_server_signs_an_agent_in_for_owners_and_admins_only():
    oauth = {
        "type": "oauth",
        "resource": "https://payroll.example.com/mcp",
        "issuer": "https://auth.example.com",
        "authorization_endpoint": "https://auth.example.com/authorize",
        "token_endpoint": "https://auth.example.com/token",
        "client_id": "client",
        "token_endpoint_auth_method": "none",
        "registered": True,
    }
    with given(_given()) as context:
        restricted = _org_server(context, "payroll", restricted=True, config={"auth": oauth, "headers": []})
        editor = _editor(context)
        path = f"{_agent_path(context)}/{restricted.id}/sign-in"

        assert_that(context.client.post(path, headers=_auth(editor)).status_code, equal_to(status.HTTP_403_FORBIDDEN))
        owner = context.client.post(path, headers=_auth(context.access_token))
        assert_that(owner.status_code, equal_to(status.HTTP_200_OK), owner.text)


def test_only_managers_restrict_a_server_and_it_is_audited():
    with given(_given()) as context:
        server = _org_server(context, "payroll")

        response = context.client.patch(
            f"{_org_path(context)}/{server.id}", json={"restricted": True}, headers=_auth(context.access_token)
        )

        assert_that(response.json(), has_entries(restricted=True))
        updated = _events(context, ORGANIZATION_MCP_SERVER_UPDATED)[-1]
        assert_that(updated.payload, has_entries(changed_fields=["restricted"], restricted=True))


def test_members_cannot_restrict_a_server():
    with given(_given()) as context:
        server = _org_server(context, "payroll")
        member, _ = _member(context)

        response = context.client.patch(
            f"{_org_path(context)}/{server.id}", json={"restricted": True}, headers=_auth(member)
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
