"""Organization MCP Servers from one Agent's side: what it starts with, and its attachments.

The contract under test:

- an Agent starts with the servers it may use: gateway URLs and a reference to a per-start
  gateway token, never a server's credential, in both runtimes' configuration;
- OpenClaw always gets the server list, empty included, so a removed server cannot survive
  on its volume;
- attaching saves the complete set of Selected Agents servers and needs `agent.update` and
  `agent.secret.manage`; restarting also needs `agent.lifecycle.manage`;
- saving while the Agent runs is allowed, and reports a pending restart until it restarts.
"""

import json
from uuid import UUID

import yaml
from fastapi import status
from hamcrest import (
    assert_that,
    contains_exactly,
    contains_string,
    equal_to,
    has_entries,
    has_key,
    is_,
    is_not,
)

from api.domains.agents.models import AgentStatus, AgentType
from api.domains.events.catalog import AGENT_UPDATED
from api.domains.events.models import OutboxMessage
from api.domains.integrations.repository import IntegrationRepository
from api.domains.mcp_servers.models import AgentMcpGatewayToken, McpServerScope, OrganizationMcpServer
from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
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

SERVER_TOKEN = "server-secret-token"
GATEWAY = "http://gateway.test:8003/gateway/v1"

_ENV = set_env_variable(
    {
        "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
        "LITELLM_BASE_URL": "http://litellm:4000",
        "LITELLM_SECRET_NAME": "litellm",
        "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
        "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        "CREDENTIAL_GATEWAY_BASE_URL": GATEWAY,
    }
)


def _given(agent_type: AgentType = AgentType.OPENCLAW, agent_status: AgentStatus = AgentStatus.STOPPED):
    return [
        _ENV,
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(email="mcp-agent-owner@example.com"),
        use_org_for_auth(),
        there_is_an_agent(agent_type=agent_type, status=agent_status),
    ]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _server(
    context, identifier: str, scope: McpServerScope = McpServerScope.SELECTED_AGENTS, **fields
) -> OrganizationMcpServer:
    credentials = {"auth": {"type": "bearer", "token": SERVER_TOKEN}, "headers": []}
    server = OrganizationMcpServer(
        organization_id=context.organization.id,
        identifier=identifier,
        name=identifier.title(),
        url=f"https://{identifier}.example.com/mcp",
        scope=scope.value,
        credentials_encrypted=encrypt_token(json.dumps(credentials), TEST_ENCRYPTION_KEY),
        **fields,
    )
    context.injector.get(PostgresRepositoryDelegate).save(server)
    return server


def _path(context) -> str:
    return f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/mcp-servers"


def _attach(context, *servers: OrganizationMcpServer, token: str | None = None, restart: bool = False):
    return context.client.put(
        _path(context),
        json={"attached_server_ids": [str(s.id) for s in servers], "restart": restart},
        headers=_auth(token or context.access_token),
    )


def _start(context):
    response = context.client.post(
        f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/start",
        headers=_auth(context.access_token),
    )
    assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
    k8s = context.injector.get(KubernetesClient)
    return k8s.create_config_map.call_args.args[1].data, k8s.create_secret.call_args.args[1].string_data


def _member(context, role: OrganizationRole = OrganizationRole.MEMBER) -> tuple[str, UUID]:
    saved = {
        name: getattr(context, name, None) for name in ("user", "organization", "organization_user", "access_token")
    }
    there_is_a_user(
        email=f"{role.value.lower()}-agent-mcp@example.com", role=role, organization_id=context.organization.id
    )(context)
    membership = context.organization_user.id
    there_is_an_access_token_for_user()(context)
    token = context.access_token
    for name, value in saved.items():
        setattr(context, name, value)
    return token, membership


# --- starting -------------------------------------------------------------------


def test_an_openclaw_agent_starts_with_gateway_urls_and_a_token_reference_only():
    with given(_given()) as context:
        _server(context, "everyone", McpServerScope.ALL_AGENTS, tool_exclude=["delete_all"])

        with when("the Agent starts with one All Agents server"):
            config_map, secret = _start(context)

        with then("OpenClaw points the server at the gateway with a reference to the token"):
            overlay = json.loads(config_map["openclaw-config-overlay.json"])
            assert_that(
                overlay["mcp"]["servers"]["everyone"],
                has_entries(
                    url=f"{GATEWAY}/mcp/everyone",
                    transport="streamable-http",
                    headers={"Authorization": "Bearer ${AF_GATEWAY_TOKEN_MCP}"},
                    toolFilter={"exclude": ["delete_all"]},
                ),
            )

        with then("the Secret holds the token, whose hash is stored for this generation"):
            token_row = context.injector.get(PostgresRepositoryDelegate).find_all(AgentMcpGatewayToken)[0]
            runtime = context.injector.get(IntegrationRepository).runtime(context.agent.id)
            assert_that(secret, has_key("AF_GATEWAY_TOKEN_MCP"))
            assert_that(token_row.generation, equal_to(runtime.generation))

        with then("the server's own credential reaches neither the ConfigMap nor the Secret"):
            assert_that(json.dumps(config_map) + json.dumps(secret), is_not(contains_string(SERVER_TOKEN)))

        with then("AGENTS.md names the server"):
            assert_that(config_map["AGENTS.md"], contains_string("## MCP servers"))
            assert_that(config_map["AGENTS.md"], contains_string("`everyone`"))


def test_a_hermes_agent_starts_with_sampling_and_elicitation_off():
    with given(_given(AgentType.HERMES)) as context:
        _server(context, "everyone", McpServerScope.ALL_AGENTS)

        config_map, _ = _start(context)

        block = yaml.safe_load(config_map["hermes-config.yaml"])["mcp_servers"]["everyone"]
        assert_that(
            block,
            has_entries(
                url=f"{GATEWAY}/mcp/everyone",
                headers={"Authorization": "Bearer ${env:AF_GATEWAY_TOKEN_MCP}"},
                sampling={"enabled": False},
                elicitation={"enabled": False},
            ),
        )


def test_an_agent_without_servers_gets_an_empty_openclaw_list_and_no_token():
    with given(_given()) as context:
        _server(context, "unattached")

        config_map, secret = _start(context)

        assert_that(json.loads(config_map["openclaw-config-overlay.json"])["mcp"], equal_to({"servers": {}}))
        assert_that("AF_GATEWAY_TOKEN_MCP" in secret, is_(False))
        assert_that(config_map["AGENTS.md"], is_not(contains_string("## MCP servers")))


# --- attaching ------------------------------------------------------------------


def test_attaching_lists_what_the_agent_may_use_and_audits_the_change():
    with given(_given()) as context:
        selected = _server(context, "selected")
        _server(context, "everyone", McpServerScope.ALL_AGENTS)
        _server(context, "off", McpServerScope.ALL_AGENTS, enabled=False)

        with when("the Owner attaches the Agent to the Selected Agents server"):
            response = _attach(context, selected)

        with then("every server is listed with whether the Agent may use it"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            body = response.json()
            assert_that(
                [(s["identifier"], s["attached"], s["active"]) for s in body["servers"]],
                contains_exactly(("everyone", False, True), ("off", False, False), ("selected", True, True)),
            )
            assert_that(body["pending_restart"], is_(False))

        with then("one agent.updated Event records the new set"):
            events = [
                m
                for m in context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
                if m.event_name == AGENT_UPDATED
            ]
            assert_that(
                events[-1].payload["field_changes"], equal_to({"mcp_servers": {"previous": [], "new": ["selected"]}})
            )


def test_only_selected_agents_servers_can_be_attached():
    with given(_given()) as context:
        everyone = _server(context, "everyone", McpServerScope.ALL_AGENTS)

        assert_that(_attach(context, everyone).status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_a_viewer_reads_but_cannot_attach():
    with given(_given()) as context:
        selected = _server(context, "selected")
        token, membership = _member(context)
        there_is_agent_access(membership_id=membership, access_role_id=AGENT_VIEWER_ROLE_ID)(context)

        with then("the Viewer reads the list"):
            read = context.client.get(_path(context), headers=_auth(token))
            assert_that(read.status_code, equal_to(status.HTTP_200_OK))

        with then("but attaching is forbidden"):
            assert_that(_attach(context, selected, token=token).status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_member_without_access_does_not_see_the_agent():
    with given(_given()) as context:
        token, _ = _member(context)

        assert_that(
            context.client.get(_path(context), headers=_auth(token)).status_code, equal_to(status.HTTP_404_NOT_FOUND)
        )


def test_attaching_to_a_running_agent_is_pending_until_it_restarts():
    with given(_given()) as context:
        selected = _server(context, "selected")
        _start(context)

        with when("the Owner attaches a server to the running Agent without restarting"):
            saved = _attach(context, selected)

        with then("it is saved and reported as pending"):
            assert_that(saved.status_code, equal_to(status.HTTP_200_OK), saved.text)
            assert_that(saved.json()["pending_restart"], is_(True))

        with when("the Owner saves again with a restart"):
            restarted = _attach(context, selected, restart=True)

        with then("the Agent runs with the server, and nothing is pending"):
            assert_that(restarted.status_code, equal_to(status.HTTP_200_OK), restarted.text)
            assert_that(restarted.json()["pending_restart"], is_(False))
            config_map = context.injector.get(KubernetesClient).create_config_map.call_args.args[1].data
            assert_that(json.loads(config_map["openclaw-config-overlay.json"])["mcp"]["servers"], has_key("selected"))


def test_disabling_a_server_a_running_agent_started_with_is_pending_too():
    with given(_given()) as context:
        _server(context, "everyone", McpServerScope.ALL_AGENTS)
        _start(context)
        server = context.injector.get(PostgresRepositoryDelegate).find_all(OrganizationMcpServer)[0]
        server.enabled = False
        context.injector.get(PostgresRepositoryDelegate).save(server)

        response = context.client.get(_path(context), headers=_auth(context.access_token))

        assert_that(response.json()["pending_restart"], is_(True))
