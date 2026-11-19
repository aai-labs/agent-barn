"""Connect to a remote MCP server once, the way an Agent's runtime will, and list its tools.

Used when a manager saves or tests an Organization MCP Server. It speaks just enough
Streamable HTTP (`initialize`, `notifications/initialized`, `tools/list`, then ending the
session) under the Custom API destination policy: public HTTPS, the address resolved
once and pinned, TLS checked against the configured hostname, and no redirects.
"""

import http.client
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from injector import singleton

from api.domains.custom_api.request import (
    PinnedHTTPSConnection,
    credential_headers,
    parse_url,
    public_addresses,
    redact,
)
from api.domains.mcp_servers.models import McpToolRead, openclaw_tool_name

PROTOCOL_VERSION = "2025-11-25"
MAX_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 15
MAX_TOOL_PAGES = 10
_CLIENT_INFO = {"name": "agent-barn-probe", "version": "1"}
USER_AGENT = "agent-barn-mcp-probe/1"


class McpProbeError(Exception):
    """The server could not be used. `refused` means it answered and rejected the credentials."""

    def __init__(self, message: str, *, refused: bool = False) -> None:
        super().__init__(message)
        self.refused = refused


@dataclass(frozen=True)
class ProbedTool:
    name: str
    description: str | None


@dataclass(frozen=True)
class ProbeResult:
    server_name: str | None
    server_version: str | None
    protocol_version: str
    offers_tools: bool
    tools: list[ProbedTool] = field(default_factory=list)


@dataclass(frozen=True)
class ToolAnalysis:
    tools: list[McpToolRead]
    warnings: list[str]
    #: OpenClaw names shared by more than one visible tool; such a server cannot be saved.
    collisions: list[str]


def analyse_tools(
    identifier: str, result: ProbeResult, include: list[str] | None, exclude: list[str] | None
) -> ToolAnalysis:
    """What Agents will see of the server's tools, and what an Admin should know about it."""
    offered = {tool.name for tool in result.tools}
    reads = []
    for tool in result.tools:
        visible = (include is None or tool.name in include) and (exclude is None or tool.name not in exclude)
        full = f"{identifier}__{tool.name}"
        reads.append(
            McpToolRead(
                name=tool.name,
                description=tool.description,
                openclaw_name=openclaw_tool_name(identifier, tool.name),
                truncated=len(full) > len(openclaw_tool_name(identifier, tool.name)),
                visible=visible,
            )
        )
    visible = [tool for tool in reads if tool.visible]
    warnings: list[str] = []
    if not result.offers_tools:
        warnings.append("The server does not offer tools.")
    elif not visible:
        warnings.append("No tools are visible to Agents with this tool filter.")
    truncated = [tool.name for tool in visible if tool.truncated]
    if truncated:
        warnings.append("OpenClaw shortens these tool names to 64 characters: " + ", ".join(truncated) + ".")
    unknown = [name for name in (include or exclude or []) if name not in offered]
    if unknown:
        warnings.append("The tool filter names tools this server does not offer: " + ", ".join(unknown) + ".")
    seen: dict[str, int] = {}
    for tool in visible:
        seen[tool.openclaw_name] = seen.get(tool.openclaw_name, 0) + 1
    collisions = sorted(name for name, count in seen.items() if count > 1)
    if collisions:
        warnings.append(
            "Several tools would share these OpenClaw names, so the server cannot be saved until the "
            "tool filter hides all but one of each: " + ", ".join(collisions) + "."
        )
    return ToolAnalysis(tools=reads, warnings=warnings, collisions=collisions)


@dataclass
class _Response:
    status: int
    headers: dict[str, str]
    body: bytes


def _messages(response: _Response) -> list[dict]:
    """JSON-RPC messages in a JSON body or an SSE stream."""
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    text = response.body.decode("utf-8", errors="replace")
    if content_type == "text/event-stream":
        messages = []
        for event in text.replace("\r\n", "\n").split("\n\n"):
            data = "\n".join(line[5:].removeprefix(" ") for line in event.split("\n") if line.startswith("data:"))
            if data:
                try:
                    messages.append(json.loads(data))
                except ValueError:
                    continue
        return [message for message in messages if isinstance(message, dict)]
    try:
        payload = json.loads(text)
    except ValueError:
        raise McpProbeError("The server did not answer with MCP messages.") from None
    return [payload] if isinstance(payload, dict) else []


@singleton
class McpServerProbe:
    """Injectable so tests can stand in for a live server."""

    #: Opens one pinned connection; replaced in unit tests.
    connect: Callable[[str, str, int], http.client.HTTPSConnection] = staticmethod(
        lambda host, address, port: PinnedHTTPSConnection(host, address, port, timeout=TIMEOUT_SECONDS)
    )

    def probe(self, url: str, config: dict) -> ProbeResult:
        """Raises `RequestRefused` for a destination or credential shape the policy refuses,
        and `McpProbeError` when the server cannot be used."""
        parsed = parse_url(url, base=True)
        port = parsed.port or 443
        headers, sensitive = credential_headers(config)
        sensitive = sorted(set(sensitive), key=len, reverse=True)
        addresses = public_addresses(parsed.hostname, port)
        target = _Target(self.connect, parsed.hostname, addresses[0], port, parsed.path or "/", headers, sensitive)
        initialized = target.call(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": _CLIENT_INFO,
            },
        )
        protocol = initialized.get("protocolVersion")
        if not isinstance(protocol, str) or not protocol:
            raise McpProbeError("The server's initialize answer has no protocol version.")
        target.protocol = protocol
        try:
            target.notify("notifications/initialized")
            info = _object(initialized.get("serverInfo"))
            offers_tools = "tools" in _object(initialized.get("capabilities"))
            tools = target.list_tools() if offers_tools else []
            return ProbeResult(
                server_name=_text(info.get("name")),
                server_version=_text(info.get("version")),
                protocol_version=protocol,
                offers_tools=offers_tools,
                tools=tools,
            )
        finally:
            target.close_session()


def _challenge(response: _Response) -> dict[str, str]:
    """The parameters of a Bearer `WWW-Authenticate` challenge, or nothing."""
    header = response.headers.get("www-authenticate", "")
    if not header.lower().startswith("bearer"):
        return {}
    return {name.lower(): value for name, value in re.findall(r'([A-Za-z_]+)="([^"]*)"', header)}


def _object(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: object, limit: int = 200) -> str | None:
    return value[:limit] if isinstance(value, str) and value else None


@dataclass
class _Target:
    connect: Callable[[str, str, int], http.client.HTTPSConnection]
    host: str
    address: str
    port: int
    path: str
    credentials: dict[str, str]
    sensitive: list[str]
    session: str | None = None
    protocol: str | None = None
    next_id: int = 1

    def _send(self, method: str, body: dict | None) -> _Response:
        headers = {
            **self.credentials,
            "accept": "application/json, text/event-stream",
            # http.client sends none, and some servers' firewalls refuse a request without one.
            "user-agent": USER_AGENT,
        }
        if body is not None:
            headers["content-type"] = "application/json"
        if self.session:
            headers["mcp-session-id"] = self.session
        if self.protocol:
            headers["mcp-protocol-version"] = self.protocol
        connection = self.connect(self.host, self.address, self.port)
        try:
            connection.request(
                method, self.path, body=json.dumps(body).encode() if body is not None else None, headers=headers
            )
            response = connection.getresponse()
            content = response.read(MAX_BYTES + 1)
            received = {name.lower(): value for name, value in response.getheaders()}
        except (OSError, http.client.HTTPException) as exc:
            raise McpProbeError("The server could not be reached.") from exc
        finally:
            connection.close()
        if len(content) > MAX_BYTES:
            raise McpProbeError("The server's answer is larger than 1 MiB.")
        return _Response(status=response.status, headers=received, body=content)

    def _check_status(self, response: _Response) -> None:
        if 300 <= response.status < 400:
            raise McpProbeError(f"The server redirected (HTTP {response.status}); redirects are not followed.")
        challenge = _challenge(response)
        # A server rejecting a bad token often answers 400 with an `invalid_token` challenge.
        rejected_token = response.status == 400 and challenge.get("error") == "invalid_token"
        if response.status in {401, 403} or rejected_token:
            raise McpProbeError(self._refusal(response.status, challenge), refused=True)
        if response.status in {404, 405} and self.session is None:
            # A web page that does not take POST answers 405; neither status is an MCP server.
            raise McpProbeError(f"No MCP server answered at this URL (HTTP {response.status}).")
        if response.status >= 400:
            raise McpProbeError(f"The server is unavailable (HTTP {response.status}).")

    def _refusal(self, status: int, challenge: dict[str, str]) -> str:
        """Why the server refused, in its own words where it gave any (`error_description`)."""
        reason = redact(challenge.get("error_description", ""), self.sensitive)
        reason = "".join(c for c in reason if c.isprintable())[:200]
        code = f"HTTP {status}" + (f": {reason}" if reason else "")
        # MCP's authorization spec: a challenge naming protected-resource metadata means the
        # server offers an OAuth sign-in. Many such servers also accept an API token.
        oauth = "resource_metadata" in challenge
        if self.sensitive:
            message = f"The server refused the credentials ({code})."
            if oauth:
                message += " If it accepts only an OAuth sign-in, Agent Barn cannot use it yet."
            return message
        if oauth:
            return (
                f"This server needs a sign-in ({code}). Agent Barn does not support OAuth sign-in yet; "
                "if the server also accepts an API token, add it as the authentication."
            )
        return f"This server needs credentials ({code})."

    def call(self, method: str, params: dict) -> dict:
        request_id = self.next_id
        self.next_id += 1
        response = self._send("POST", {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        self._check_status(response)
        if method == "initialize":
            self.session = response.headers.get("mcp-session-id") or None
        answer = next((m for m in _messages(response) if m.get("id") == request_id), None)
        if answer is None:
            raise McpProbeError(f"The server did not answer {method}.")
        if "error" in answer:
            error = answer["error"] if isinstance(answer["error"], dict) else {}
            message = redact(str(error.get("message", "unknown error"))[:200], self.sensitive)
            raise McpProbeError(f"The server answered {method} with an error: {message}")
        result = answer.get("result")
        if not isinstance(result, dict):
            raise McpProbeError(f"The server's answer to {method} is not an MCP result.")
        return result

    def notify(self, method: str) -> None:
        self._check_status(self._send("POST", {"jsonrpc": "2.0", "method": method}))

    def list_tools(self) -> list[ProbedTool]:
        tools: list[ProbedTool] = []
        cursor = None
        for _ in range(MAX_TOOL_PAGES):
            result = self.call("tools/list", {"cursor": cursor} if cursor else {})
            for tool in result.get("tools") or []:
                if isinstance(tool, dict) and isinstance(tool.get("name"), str) and tool["name"]:
                    tools.append(ProbedTool(name=tool["name"][:128], description=_text(tool.get("description"), 500)))
            cursor = result.get("nextCursor")
            if not isinstance(cursor, str) or not cursor:
                return tools
        raise McpProbeError(f"The server lists more than {MAX_TOOL_PAGES} pages of tools.")

    def close_session(self) -> None:
        if not self.session:
            return
        try:
            self._send("DELETE", None)
        except McpProbeError:
            pass
