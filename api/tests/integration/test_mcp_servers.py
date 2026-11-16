"""Organization MCP Servers: an Organization's remote MCP servers and their one credential.

The contract under test:

- any member lists the Organization's servers, but only `mcp_server.manage` (Owners and
  Admins) sees a server's URL and authentication, or creates, changes, probes or deletes one;
- saving connects to the server once, so a wrong URL or key, or a tool filter whose names
  would collide in OpenClaw, fails the save and leaves nothing behind;
- saved secrets are never read back and carry over on update within the same scheme;
- each change stages one audit Event without the credential or the URL's path, and an
  unchanged save stages none;
- deleting a server removes its attachments with it;
- the servers an Agent may use come only from its own Organization: enabled ones with All
  Agents, or Selected Agents ones it is attached to.
"""

from typing import Any
from uuid import UUID, uuid7

import pytest
from fastapi import status
from hamcrest import (
    assert_that,
    contains_exactly,
    contains_string,
    empty,
    equal_to,
    has_entries,
    has_length,
    is_not,
    none,
)
from injector import Module, provider, singleton
from sqlalchemy.exc import IntegrityError

from api.domains.custom_api.request import RequestRefused
from api.domains.events.catalog import (
    ORGANIZATION_MCP_SERVER_CREATED,
    ORGANIZATION_MCP_SERVER_DELETED,
    ORGANIZATION_MCP_SERVER_UPDATED,
)
from api.domains.events.models import OutboxMessage
from api.domains.mcp_servers.models import AgentMcpServerAttachment, OrganizationMcpServer
from api.domains.mcp_servers.probe import McpProbeError, McpServerProbe, ProbedTool, ProbeResult
from api.domains.mcp_servers.repository import McpServerRepository
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization, there_is_an_organization_with_user_and_access_token
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_SERVERS = "/api/v1/organizations/{organization_id}/mcp-servers"
_TOKEN = "lin_api_secret_value"


class FakeProbe(McpServerProbe):
    """Stands in for a live MCP server and records what each probe was given."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.tools = ["search_issues", "create_issue"]
        self.failure: Exception | None = None

    def probe(self, url: str, config: dict) -> ProbeResult:
        self.calls.append((url, config))
        if self.failure is not None:
            raise self.failure
        return ProbeResult(
            server_name="linear",
            server_version="1.0",
            protocol_version="2025-11-25",
            offers_tools=True,
            tools=[ProbedTool(name=name, description=None) for name in self.tools],
        )


class FakeProbeModule(Module):
    def __init__(self, probe: FakeProbe) -> None:
        self.probe = probe

    @provider
    @singleton
    def provide_probe(self) -> McpServerProbe:
        return self.probe


def _given(probe: FakeProbe, role: OrganizationRole = OrganizationRole.OWNER):
    return [
        set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), FakeProbeModule(probe)]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(email="mcp-owner@example.com", role=role),
        use_org_for_auth(),
    ]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _member(context, role: OrganizationRole, *, organization_id: UUID | None = None) -> str:
    """A Membership's token, without replacing the test's Owner as the actor."""
    saved = {
        name: getattr(context, name, None) for name in ("user", "organization", "organization_user", "access_token")
    }
    user_id = uuid7()
    there_is_a_user(
        id=user_id,
        email=f"{role.value.lower()}-{user_id}@example.com",
        role=role,
        organization_id=organization_id or context.organization.id,
    )(context)
    there_is_an_access_token_for_user(user_id)(context)
    token = context.access_token
    for name, value in saved.items():
        setattr(context, name, value)
    return token


def _body(**overrides: Any) -> dict:
    return {
        "name": "Linear Prod",
        "description": "Issue tracker",
        "url": "https://mcp.linear.app/mcp",
        "scope": "selected_agents",
        "auth": {"type": "bearer", "token": _TOKEN},
        "headers": [{"name": "X-Workspace", "value": "acme"}, {"name": "X-Signing", "value": "sig-1", "secret": True}],
        **overrides,
    }


def _create(context, token: str | None = None, **overrides: Any):
    return context.client.post(_SERVERS, json=_body(**overrides), headers=_auth(token or context.access_token))


def _created(context, **overrides: Any) -> dict:
    response = _create(context, **overrides)
    assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)
    return response.json()


def _events(context, name: str) -> list[OutboxMessage]:
    return [m for m in context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage) if m.event_name == name]


def _attach(context, agent_id: UUID, server_id: str, organization_id: UUID | None = None) -> None:
    context.injector.get(PostgresRepositoryDelegate).save(
        AgentMcpServerAttachment(
            organization_id=organization_id or context.organization.id,
            agent_id=agent_id,
            mcp_server_id=UUID(server_id),
        )
    )


# --- creating -----------------------------------------------------------------


def test_an_owner_registers_a_server_and_reads_it_back_without_its_secrets():
    probe = FakeProbe()
    with given(_given(probe)) as context:
        with when("the Owner registers a server with a bearer token and a secret header"):
            response = _create(context)

        with then("it is saved under an identifier from its name, with no secret value in the answer"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)
            body = response.json()
            assert_that(
                body,
                has_entries(
                    identifier="linear-prod",
                    name="Linear Prod",
                    url="https://mcp.linear.app/mcp",
                    scope="selected_agents",
                    enabled=True,
                    auth_type="bearer",
                    attachment_count=0,
                    agent_count=0,
                ),
            )
            assert_that(
                body["headers"],
                contains_exactly(
                    has_entries(name="X-Workspace", secret=False, value="acme"),
                    has_entries(name="X-Signing", secret=True, value=None),
                ),
            )
            assert_that(response.text, is_not(contains_string(_TOKEN)))
            assert_that(response.text, is_not(contains_string("sig-1")))

        with then("the server was connected to once, with the credential"):
            assert_that(probe.calls, has_length(1))
            assert_that(probe.calls[0][1]["auth"], equal_to({"type": "bearer", "token": _TOKEN}))


def test_creating_stages_one_event_with_the_host_but_no_credential():
    with given(_given(FakeProbe())) as context:
        with when("the Owner registers a server whose URL path could carry a key"):
            _created(context, url="https://mcp.example.com/k/abc123/mcp")

        with then("one Event records the host, the scheme and no secret"):
            events = _events(context, ORGANIZATION_MCP_SERVER_CREATED)
            assert_that(events, has_length(1))
            assert_that(
                events[0].payload,
                has_entries(
                    identifier="linear-prod", url_host="mcp.example.com", auth_type="bearer", scope="selected_agents"
                ),
            )
            assert_that(str(events[0].payload), is_not(contains_string("abc123")))
            assert_that(str(events[0].payload), is_not(contains_string(_TOKEN)))


def test_an_admin_may_register_a_server():
    with given(_given(FakeProbe())) as context:
        admin = _member(context, OrganizationRole.ADMIN)

        assert_that(_create(context, admin).status_code, equal_to(status.HTTP_201_CREATED))


def test_a_member_cannot_register_a_server():
    probe = FakeProbe()
    with given(_given(probe)) as context:
        member = _member(context, OrganizationRole.MEMBER)

        with when("a Member tries to register a server"):
            response = _create(context, member)

        with then("it is refused before anything is contacted"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(probe.calls, empty())


def test_a_second_server_with_the_same_identifier_conflicts():
    with given(_given(FakeProbe())) as context:
        _created(context)

        response = _create(context, name="linear  PROD")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(response.json()["detail"], contains_string("linear-prod"))


@pytest.mark.parametrize(
    "url",
    ["http://mcp.example.com/mcp", "https://user:pw@mcp.example.com/mcp", "https://mcp.example.com/mcp?key=1"],
)
def test_a_url_that_is_not_plain_public_https_is_refused(url: str):
    probe = FakeProbe()
    with given(_given(probe)) as context:
        response = _create(context, url=url)

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
        assert_that(probe.calls, empty())


def test_a_server_that_refuses_the_credential_is_not_saved():
    probe = FakeProbe()
    with given(_given(probe)) as context:
        probe.failure = McpProbeError("The server refused the credentials (HTTP 401).", refused=True)

        with when("the Owner registers a server that rejects the token"):
            response = _create(context)

        with then("the save fails with the reason, and nothing is stored or audited"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("HTTP 401"))
            assert_that(context.injector.get(PostgresRepositoryDelegate).find_all(OrganizationMcpServer), empty())
            assert_that(_events(context, ORGANIZATION_MCP_SERVER_CREATED), empty())


def test_a_server_at_a_private_address_is_refused():
    probe = FakeProbe()
    with given(_given(probe)) as context:
        probe.failure = RequestRefused("Destination resolves to a non-public address")

        response = _create(context, url="https://internal.example.com/mcp")

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))


def test_a_tool_filter_whose_names_collide_in_openclaw_is_refused():
    probe = FakeProbe()
    with given(_given(probe)) as context:
        prefix = "summarize_the_entire_knowledge_base_for_the_quarterly_review"
        probe.tools = [prefix + "_one", prefix + "_two"]

        with when("both tools stay visible and OpenClaw would cut them to one name"):
            response = _create(context)

        with then("the save is refused and says which name collides"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("linear-prod__summarize"))

        with then("hiding one of them lets the server be saved"):
            assert_that(_create(context, tool_exclude=[prefix + "_two"]).status_code, equal_to(status.HTTP_201_CREATED))


# --- reading ------------------------------------------------------------------


def test_a_member_lists_servers_without_their_url_or_authentication():
    with given(_given(FakeProbe())) as context:
        _created(context, url="https://mcp.example.com/k/abc123/mcp")
        member = _member(context, OrganizationRole.MEMBER)

        with when("a Member lists the Organization's servers"):
            response = context.client.get(_SERVERS, headers=_auth(member))

        with then("they see what the server is, but not where it lives or how it authenticates"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                response.json(),
                contains_exactly(has_entries(identifier="linear-prod", url=none(), auth_type=none(), headers=empty())),
            )
            assert_that(response.text, is_not(contains_string("abc123")))


def test_someone_from_another_organization_cannot_list_the_servers():
    with given(_given(FakeProbe())) as context:
        _created(context)
        outsider = _member(context, OrganizationRole.OWNER, organization_id=uuid7())

        assert_that(
            context.client.get(_SERVERS, headers=_auth(outsider)).status_code, equal_to(status.HTTP_403_FORBIDDEN)
        )


def test_a_server_from_another_organization_is_not_found():
    with given(_given(FakeProbe())) as context:
        mine = context.organization
        theirs = uuid7()
        there_is_an_organization(id=theirs, name="Other")(context)
        context.organization = mine
        other = OrganizationMcpServer(
            organization_id=theirs,
            identifier="other",
            name="Other",
            url="https://o.example.com/mcp",
            credentials_encrypted="x",
        )
        context.injector.get(PostgresRepositoryDelegate).save(other)

        response = context.client.get(f"{_SERVERS}/{other.id}", headers=_auth(context.access_token))

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_counts_follow_the_scope_and_skip_deleted_agents():
    with given(_given(FakeProbe())) as context:
        server = _created(context)
        there_is_an_agent(name="Attached")(context)
        _attach(context, context.agent.id, server["id"])
        there_is_an_agent(name="Gone", deleted=True)(context)
        _attach(context, context.agent.id, server["id"])
        there_is_an_agent(name="Other")(context)

        with when("the server is Selected Agents, then All Agents"):
            selected = context.client.get(f"{_SERVERS}/{server['id']}", headers=_auth(context.access_token)).json()
            context.client.patch(
                f"{_SERVERS}/{server['id']}", json={"scope": "all_agents"}, headers=_auth(context.access_token)
            )
            everyone = context.client.get(f"{_SERVERS}/{server['id']}", headers=_auth(context.access_token)).json()

        with then("Selected Agents reaches its live attachment; All Agents reaches every live Agent"):
            assert_that(selected, has_entries(attachment_count=1, agent_count=1))
            assert_that(everyone, has_entries(attachment_count=1, agent_count=2))


# --- updating -----------------------------------------------------------------


def test_resending_the_scheme_without_the_token_keeps_the_saved_token():
    probe = FakeProbe()
    with given(_given(probe)) as context:
        server = _created(context)

        with when("the Owner changes the URL and resends bearer auth and the secret header without values"):
            response = context.client.patch(
                f"{_SERVERS}/{server['id']}",
                json={
                    "url": "https://mcp2.linear.app/mcp",
                    "auth": {"type": "bearer"},
                    "headers": [{"name": "X-Signing", "secret": True}],
                },
                headers=_auth(context.access_token),
            )

        with then("the new URL is probed with the saved token and the saved secret header"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            url, config = probe.calls[-1]
            assert_that(url, equal_to("https://mcp2.linear.app/mcp"))
            assert_that(config["auth"], equal_to({"type": "bearer", "token": _TOKEN}))
            assert_that(config["headers"], equal_to([{"name": "X-Signing", "value": "sig-1", "secret": True}]))

        with then("one update Event names what changed"):
            events = _events(context, ORGANIZATION_MCP_SERVER_UPDATED)
            assert_that(events, has_length(1))
            assert_that(events[0].payload["changed_fields"], equal_to(["url", "headers"]))


def test_a_new_header_name_for_an_api_key_needs_the_key_again():
    probe = FakeProbe()
    with given(_given(probe)) as context:
        server = _created(context, auth={"type": "api_key", "header_name": "X-Api-Key", "token": _TOKEN})

        response = context.client.patch(
            f"{_SERVERS}/{server['id']}",
            json={"auth": {"type": "api_key", "header_name": "X-Other-Key"}},
            headers=_auth(context.access_token),
        )

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))


def test_renaming_or_rescoping_does_not_contact_the_server_or_change_the_identifier():
    probe = FakeProbe()
    with given(_given(probe)) as context:
        server = _created(context)

        with when("the Owner renames the server, rescopes it and disables it"):
            response = context.client.patch(
                f"{_SERVERS}/{server['id']}",
                json={"name": "Linear", "scope": "all_agents", "enabled": False},
                headers=_auth(context.access_token),
            )

        with then("the identifier stays, and no probe ran after the create"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                response.json(), has_entries(identifier="linear-prod", name="Linear", scope="all_agents", enabled=False)
            )
            assert_that(probe.calls, has_length(1))


def test_switching_from_an_exclude_list_to_an_include_list_replaces_the_filter():
    with given(_given(FakeProbe())) as context:
        server = _created(context, tool_exclude=["create_issue"])

        response = context.client.patch(
            f"{_SERVERS}/{server['id']}", json={"tool_include": ["search_issues"]}, headers=_auth(context.access_token)
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(response.json(), has_entries(tool_include=["search_issues"], tool_exclude=none()))


def test_an_unchanged_save_records_nothing():
    probe = FakeProbe()
    with given(_given(probe)) as context:
        server = _created(context)

        context.client.patch(
            f"{_SERVERS}/{server['id']}",
            json={"name": "Linear Prod", "auth": {"type": "bearer"}},
            headers=_auth(context.access_token),
        )

        assert_that(_events(context, ORGANIZATION_MCP_SERVER_UPDATED), empty())
        assert_that(probe.calls, has_length(1))


def test_a_member_cannot_change_a_server():
    with given(_given(FakeProbe())) as context:
        server = _created(context)
        member = _member(context, OrganizationRole.MEMBER)

        response = context.client.patch(f"{_SERVERS}/{server['id']}", json={"enabled": False}, headers=_auth(member))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


# --- probing ------------------------------------------------------------------


def test_probing_a_saved_server_with_a_draft_filter_reports_visibility_without_saving():
    probe = FakeProbe()
    with given(_given(probe)) as context:
        server = _created(context)

        with when("the Owner tests the saved server with an include list it has not saved"):
            response = context.client.post(
                f"{_SERVERS}/{server['id']}/probe",
                json={"tool_include": ["search_issues", "missing_tool"]},
                headers=_auth(context.access_token),
            )

        with then("each tool reports whether Agents would see it, with a warning for the unknown name"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            body = response.json()
            assert_that(
                body["tools"],
                contains_exactly(
                    has_entries(name="search_issues", visible=True, openclaw_name="linear-prod__search_issues"),
                    has_entries(name="create_issue", visible=False),
                ),
            )
            assert_that(body["warnings"], contains_exactly(contains_string("missing_tool")))

        with then("the saved filter is untouched"):
            saved = context.client.get(f"{_SERVERS}/{server['id']}", headers=_auth(context.access_token)).json()
            assert_that(saved["tool_include"], none())


def test_probing_an_unsaved_server_names_tools_for_the_identifier_its_name_would_get():
    with given(_given(FakeProbe())) as context:
        response = context.client.post(
            f"{_SERVERS}/probe",
            json={"name": "Docs", "url": "https://docs.example.com/mcp"},
            headers=_auth(context.access_token),
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(response.json()["tools"][0]["openclaw_name"], equal_to("docs__search_issues"))


def test_a_member_cannot_probe():
    probe = FakeProbe()
    with given(_given(probe)) as context:
        member = _member(context, OrganizationRole.MEMBER)

        response = context.client.post(
            f"{_SERVERS}/probe", json={"url": "https://docs.example.com/mcp"}, headers=_auth(member)
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(probe.calls, empty())


# --- deleting -----------------------------------------------------------------


def test_deleting_a_server_removes_its_attachments_and_audits_how_many():
    with given(_given(FakeProbe())) as context:
        server = _created(context)
        there_is_an_agent()(context)
        _attach(context, context.agent.id, server["id"])

        with when("the Owner deletes a server one Agent is attached to"):
            response = context.client.delete(f"{_SERVERS}/{server['id']}", headers=_auth(context.access_token))

        with then("the server and its attachment are gone"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            delegate = context.injector.get(PostgresRepositoryDelegate)
            assert_that(delegate.find_all(OrganizationMcpServer), empty())
            assert_that(delegate.find_all(AgentMcpServerAttachment), empty())

        with then("the Event records the attachment it took with it"):
            events = _events(context, ORGANIZATION_MCP_SERVER_DELETED)
            assert_that(events, has_length(1))
            assert_that(events[0].payload, has_entries(identifier="linear-prod", attachment_count=1))


def test_a_member_cannot_delete_a_server():
    with given(_given(FakeProbe())) as context:
        server = _created(context)
        member = _member(context, OrganizationRole.MEMBER)

        response = context.client.delete(f"{_SERVERS}/{server['id']}", headers=_auth(member))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


# --- which servers an Agent may use -------------------------------------------


def _effective(context, agent_id: UUID) -> list[str]:
    return [server.identifier for server in context.injector.get(McpServerRepository).effective_for_agent(agent_id)]


def test_an_agent_may_use_enabled_all_agents_servers_and_the_selected_ones_it_is_attached_to():
    with given(_given(FakeProbe())) as context:
        _created(context, name="Everyone", scope="all_agents")
        _created(context, name="Off", scope="all_agents", enabled=False)
        attached = _created(context, name="Attached")
        _created(context, name="Not Attached")
        there_is_an_agent()(context)
        _attach(context, context.agent.id, attached["id"])

        assert_that(_effective(context, context.agent.id), contains_exactly("attached", "everyone"))


def test_a_deleted_agent_may_use_no_server():
    with given(_given(FakeProbe())) as context:
        _created(context, name="Everyone", scope="all_agents")
        there_is_an_agent(deleted=True)(context)

        assert_that(_effective(context, context.agent.id), empty())


def test_another_organizations_servers_never_reach_an_agent():
    with given(_given(FakeProbe())) as context:
        _created(context, name="Everyone", scope="all_agents")
        mine = context.organization
        theirs = uuid7()
        there_is_an_organization(id=theirs, name="Other")(context)
        there_is_an_agent(organization_id=theirs)(context)
        context.organization = mine

        assert_that(_effective(context, context.agent.id), empty())


def test_an_attachment_across_organizations_is_refused_by_the_database():
    with given(_given(FakeProbe())) as context:
        server = _created(context)
        mine = context.organization
        theirs = uuid7()
        there_is_an_organization(id=theirs, name="Other")(context)
        there_is_an_agent(organization_id=theirs)(context)
        context.organization = mine

        with pytest.raises(IntegrityError):
            _attach(context, context.agent.id, server["id"], organization_id=theirs)
