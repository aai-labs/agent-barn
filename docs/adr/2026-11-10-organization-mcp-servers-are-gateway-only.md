# Organization MCP Servers are reached only through the credential gateway

Status: Accepted
Date: 2026-11-10
Origin: Maintainer decision opening the [Organization MCP Servers epic](../features/mcp-servers/CHANGELOG.md)
Related: [Agent pods never hold provider credentials](2026-09-02-credential-gateway-egress-modes.md), [Optional per-Agent isolation](2026-10-08-optional-agent-integration-isolation.md)

An Organization MCP Server holds one credential that an Owner or Admin owns, and many Agents use it. Those Agents are created and edited by Members who never saw that credential. Every MCP request from an Agent therefore goes through the credential gateway, and there is no direct mode. The pod receives only a per-start gateway token. The gateway resolves that token and the Agent's current access to the server on every request, injects the server's credential, and forwards to the upstream server.

## Why not the Integrations isolation switch

[Optional per-Agent isolation](2026-10-08-optional-agent-integration-isolation.md) defaults direct mode on so that a person can turn the gateway off for their own Agent's credentials when gateway routing breaks. That trade does not hold here.

- **The wrong person makes the choice.** Hermes and OpenClaw run arbitrary shell. A direct-mode MCP header would sit in the environment of every Agent that can reach the server. Any Member who can create or edit such an Agent could then read the Organization's credential. The person flipping a per-Agent switch is not the credential's owner, so the switch would not be theirs to flip.
- **A direct-only design has the same exposure for every Agent.** It also loses the gateway's live control.

## What the gateway gives

- **Live removal.** Disabling, detaching or deleting a server, and rotating or re-pointing it, take effect on the Agent's next request without a restart. Only a newly available server waits for the Agent's next start, because both runtimes read MCP configuration at boot.
- **One place to filter tools.** The gateway refuses excluded `tools/call` requests and filters `tools/list`. This is the boundary, because an Agent holding its gateway token can bypass any filter written into its own runtime configuration.
- **No credential in the pod**, in line with [the gateway's original decision](2026-09-02-credential-gateway-egress-modes.md).

## Evidence

Both pinned runtime clients (Hermes v2026.8.19 and OpenClaw 2026.8.2) were run against a stub of this route in a real agent turn:

- the runtime read the gateway token from the environment into the MCP `Authorization` header;
- both accepted `405` for the server-to-client GET stream, including Hermes's HEAD and GET preflight;
- the session ID round-tripped, and SSE replies parsed;
- both honoured a filtered `tools/list`.

So this decision needs no runtime image change and no client patch.

## Consequences

- **Streaming.** MCP Streamable HTTP answers a POST with a JSON body or an SSE stream. The gateway gets an async streaming route of its own and does not reuse the buffered, thread-pooled forwarder behind `/p/<provider>`. Stream duration, size and per-server concurrency are bounded so that one slow server cannot starve other gateway traffic.
- **No escape hatch.** If the gateway cannot carry a particular MCP server, that server is unsupported until the gateway is fixed. Agents never fall back to direct.
- **Availability.** The gateway joins the request path of every MCP tool call, in addition to the Integration traffic it already carries.
- **Upstream refusals reach the model.** OpenClaw passes the gateway's response body to the model verbatim. A refusal for a valid token whose server is no longer available therefore carries one fixed, readable message with no internals. Invalid tokens still get the gateway's opaque 403.
- **Later credential types stay gateway-held.** OAuth-protected MCP servers keep their refresh grant in the gateway as well.

## Revisit when

- An MCP server Organizations need cannot work without the server-to-client GET stream, or without a transport the gateway cannot proxy.
- Agent egress confinement or per-Agent credentials change who could read a credential placed in the pod.
