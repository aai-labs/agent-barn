from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Response, status
from fastapi.responses import HTMLResponse
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.mcp_servers.agent_service import AgentMcpServerService
from api.domains.mcp_servers.models import (
    AgentMcpCredentialUpdate,
    AgentMcpServerCreate,
    AgentMcpServersRead,
    AgentMcpServersUpdate,
    AgentMcpServerUpdate,
    McpServerCreate,
    McpServerProbeRead,
    McpServerProbeRequest,
    McpServerRead,
    McpServerUpdate,
    McpSignInComplete,
    McpSignInResult,
    McpSignInStart,
)
from api.domains.mcp_servers.service import McpServerService
from api.domains.mcp_servers.sign_in import McpSignInService

mcp_servers_router = APIRouter(prefix="/organizations/{organization_id}/mcp-servers", tags=["mcp-servers"])

_Service = Annotated[McpServerService, Injected(McpServerService)]
_Context = Annotated[CurrentUserContext, Depends(get_current_user())]
_SignIn = Annotated[McpSignInService, Injected(McpSignInService)]


@mcp_servers_router.get("", response_model=list[McpServerRead])
def list_mcp_servers(organization_id: UUID, context: _Context, service: _Service):
    return service.list_servers(organization_id, context)


@mcp_servers_router.post("", response_model=McpServerRead, status_code=status.HTTP_201_CREATED)
def create_mcp_server(organization_id: UUID, data: McpServerCreate, context: _Context, service: _Service):
    return service.create_server(organization_id, data, context)


@mcp_servers_router.post("/probe", response_model=McpServerProbeRead)
def probe_new_mcp_server(organization_id: UUID, data: McpServerProbeRequest, context: _Context, service: _Service):
    return service.probe_new(organization_id, data, context)


# Declared before the `/{server_id}` routes so `sign-in` is never read as a server id.
@mcp_servers_router.post("/sign-in/complete", response_model=McpSignInResult)
def complete_mcp_server_sign_in(organization_id: UUID, data: McpSignInComplete, context: _Context, sign_in: _SignIn):
    """Finishes an Organization or Agent sign-in with the code the popup received."""
    return sign_in.complete(organization_id, data.code, data.state, context)


@mcp_servers_router.get("/{server_id}", response_model=McpServerRead)
def get_mcp_server(organization_id: UUID, server_id: UUID, context: _Context, service: _Service):
    return service.get_server(organization_id, server_id, context)


@mcp_servers_router.patch("/{server_id}", response_model=McpServerRead)
def update_mcp_server(
    organization_id: UUID, server_id: UUID, data: McpServerUpdate, context: _Context, service: _Service
):
    return service.update_server(organization_id, server_id, data, context)


@mcp_servers_router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mcp_server(organization_id: UUID, server_id: UUID, context: _Context, service: _Service):
    service.delete_server(organization_id, server_id, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@mcp_servers_router.post("/{server_id}/probe", response_model=McpServerProbeRead)
def probe_mcp_server(
    organization_id: UUID,
    server_id: UUID,
    context: _Context,
    service: _Service,
    data: Annotated[McpServerUpdate | None, Body()] = None,
):
    return service.probe_saved(organization_id, server_id, data, context)


agent_mcp_servers_router = APIRouter(
    prefix="/organizations/{organization_id}/agents/{agent_id}/mcp-servers", tags=["mcp-servers"]
)
_AgentService = Annotated[AgentMcpServerService, Injected(AgentMcpServerService)]


@agent_mcp_servers_router.get("", response_model=AgentMcpServersRead)
def list_agent_mcp_servers(agent_id: UUID, context: _Context, service: _AgentService):
    return service.read(agent_id, context)


@agent_mcp_servers_router.put("", response_model=AgentMcpServersRead)
def update_agent_mcp_servers(agent_id: UUID, data: AgentMcpServersUpdate, context: _Context, service: _AgentService):
    return service.update(agent_id, data, context)


@agent_mcp_servers_router.post("", response_model=McpServerRead, status_code=status.HTTP_201_CREATED)
def create_agent_own_mcp_server(agent_id: UUID, data: AgentMcpServerCreate, context: _Context, service: _AgentService):
    """Adds an MCP server for this Agent only."""
    return service.create_own(agent_id, data, context)


@agent_mcp_servers_router.post("/probe", response_model=McpServerProbeRead)
def probe_new_agent_own_mcp_server(
    agent_id: UUID, data: McpServerProbeRequest, context: _Context, service: _AgentService
):
    return service.probe_own_new(agent_id, data, context)


@agent_mcp_servers_router.patch("/{server_id}", response_model=McpServerRead)
def update_agent_own_mcp_server(
    agent_id: UUID, server_id: UUID, data: AgentMcpServerUpdate, context: _Context, service: _AgentService
):
    return service.update_own(agent_id, server_id, data, context)


@agent_mcp_servers_router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_own_mcp_server(agent_id: UUID, server_id: UUID, context: _Context, service: _AgentService):
    service.delete_own(agent_id, server_id, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@agent_mcp_servers_router.post("/{server_id}/probe", response_model=McpServerProbeRead)
def probe_agent_own_mcp_server(
    agent_id: UUID,
    server_id: UUID,
    context: _Context,
    service: _AgentService,
    data: Annotated[AgentMcpServerUpdate | None, Body()] = None,
):
    return service.probe_own_saved(agent_id, server_id, data, context)


@mcp_servers_router.post("/{server_id}/sign-in", response_model=McpSignInStart)
def start_mcp_server_sign_in(organization_id: UUID, server_id: UUID, context: _Context, sign_in: _SignIn):
    """Starts the Organization sign-in of an OAuth server."""
    return sign_in.start(organization_id, server_id, None, context)


@mcp_servers_router.delete("/{server_id}/sign-in", status_code=status.HTTP_204_NO_CONTENT)
def remove_mcp_server_sign_in(organization_id: UUID, server_id: UUID, context: _Context, sign_in: _SignIn):
    sign_in.sign_out(organization_id, server_id, None, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@agent_mcp_servers_router.put("/{server_id}/credential", response_model=AgentMcpServersRead)
def set_agent_mcp_server_credential(
    agent_id: UUID, server_id: UUID, data: AgentMcpCredentialUpdate, context: _Context, service: _AgentService
):
    """The Agent's own token and headers for a token-based server."""
    return service.set_credential(agent_id, server_id, data, context)


@agent_mcp_servers_router.delete("/{server_id}/credential", status_code=status.HTTP_204_NO_CONTENT)
def remove_agent_mcp_server_credential(
    organization_id: UUID, agent_id: UUID, server_id: UUID, context: _Context, sign_in: _SignIn
):
    """Removes the Agent's own credential of either kind; it goes back to the Organization's."""
    sign_in.sign_out(organization_id, server_id, agent_id, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@agent_mcp_servers_router.post("/{server_id}/sign-in", response_model=McpSignInStart)
def start_agent_mcp_server_sign_in(
    organization_id: UUID, agent_id: UUID, server_id: UUID, context: _Context, sign_in: _SignIn
):
    """Starts the Agent's own sign-in of an OAuth server."""
    return sign_in.start(organization_id, server_id, agent_id, context)


# Fixed and organization-independent: it is the redirect URI every registered client carries.
mcp_oauth_callback_router = APIRouter(prefix="/mcp-servers/oauth", tags=["mcp-servers"])


@mcp_oauth_callback_router.get("/callback", response_class=HTMLResponse)
def mcp_server_sign_in_callback(
    sign_in: _SignIn,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    return sign_in.callback_page(code, state, error)
