"""How an Agent's runtime is told about the Organization MCP Servers it may use.

Every server points at the credential gateway's MCP route, never at the server itself, and
carries only a reference to the per-start gateway token, which the pod's Secret holds. The
ConfigMap therefore holds no credential, and the server's own credential never reaches the pod.
Both runtimes resolve the reference from the environment when they read their config.
"""

from api.domains.mcp_servers.models import OrganizationMcpServer

#: The pod Secret entry holding the generation's MCP gateway token.
GATEWAY_TOKEN_ENV = "AF_GATEWAY_TOKEN_MCP"
#: Matches the gateway's own stream limit, so the runtime does not give up before the gateway.
TOOL_TIMEOUT_SECONDS = 300
CONNECT_TIMEOUT_SECONDS = 30
SNAPSHOT_KEY = "mcp_servers"


def server_url(gateway_base_url: str, server: OrganizationMcpServer) -> str:
    return f"{gateway_base_url.rstrip('/')}/mcp/{server.identifier}"


def snapshot(servers: list[OrganizationMcpServer]) -> dict[str, dict]:
    """What the integration runtime records about the servers a generation started with.

    Absent when there are none, so Agents without servers keep their snapshot unchanged.
    """
    if not servers:
        return {}
    return {SNAPSHOT_KEY: {"identifiers": sorted(server.identifier for server in servers)}}


def started_identifiers(bindings: dict) -> set[str]:
    return set(bindings.get(SNAPSHOT_KEY, {}).get("identifiers", []))


def _filter(server: OrganizationMcpServer) -> dict[str, list[str]]:
    if server.tool_include is not None:
        return {"include": list(server.tool_include)}
    if server.tool_exclude is not None:
        return {"exclude": list(server.tool_exclude)}
    return {}


def hermes_mcp_servers(servers: list[OrganizationMcpServer], gateway_base_url: str) -> dict[str, dict]:
    """Hermes `mcp_servers`. Sampling and elicitation are off: a server may neither spend the
    Organization's model budget through the Agent nor ask the Agent's user for input."""
    blocks: dict[str, dict] = {}
    for server in servers:
        block: dict = {
            "url": server_url(gateway_base_url, server),
            "headers": {"Authorization": "Bearer ${env:" + GATEWAY_TOKEN_ENV + "}"},
            "timeout": TOOL_TIMEOUT_SECONDS,
            "connect_timeout": CONNECT_TIMEOUT_SECONDS,
            "sampling": {"enabled": False},
            "elicitation": {"enabled": False},
        }
        if tools := _filter(server):
            # The gateway enforces the filter; this only keeps hidden tools out of the prompt.
            block["tools"] = tools
        blocks[server.identifier] = block
    return blocks


def openclaw_mcp_servers(servers: list[OrganizationMcpServer], gateway_base_url: str) -> dict[str, dict]:
    """OpenClaw `mcp.servers`; OpenClaw advertises neither sampling nor elicitation."""
    blocks: dict[str, dict] = {}
    for server in servers:
        block: dict = {
            "url": server_url(gateway_base_url, server),
            "transport": "streamable-http",
            "enabled": True,
            "headers": {"Authorization": "Bearer ${" + GATEWAY_TOKEN_ENV + "}"},
            "connectionTimeoutMs": CONNECT_TIMEOUT_SECONDS * 1000,
            "requestTimeoutMs": TOOL_TIMEOUT_SECONDS * 1000,
        }
        if tools := _filter(server):
            block["toolFilter"] = tools
        blocks[server.identifier] = block
    return blocks


def policy_md(servers: list[OrganizationMcpServer]) -> str:
    """The AGENTS.md block naming the servers. It names no URL, token or command: Hermes
    refuses an AGENTS.md that shows credential handling, and the Agent needs neither."""
    if not servers:
        return ""
    lines = [
        f"- `{server.identifier}`: {server.name}" + (f". {server.description}" if server.description else "")
        for server in servers
    ]
    return (
        "\n\n## MCP servers\n\n"
        "These MCP servers are connected for you. Their tools are among your tools, "
        "named after the server:\n\n"
        + "\n".join(lines)
        + "\n\nUse them like any other tool. If a call answers that the server is no longer "
        "available, it has been removed; do not retry it.\n"
    )
