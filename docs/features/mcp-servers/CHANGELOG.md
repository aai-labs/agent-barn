# Organization MCP Servers — change log

Status: Active
Epic: Organization MCP Servers (no ticket yet)
Related context: [`../mcp-servers.md`](../mcp-servers.md), [`../integrations.md`](../integrations.md#custom-api-connections), [`../credential-gateway/CHANGELOG.md`](../credential-gateway/CHANGELOG.md), [`../../adr/2026-11-10-organization-mcp-servers-are-gateway-only.md`](../../adr/2026-11-10-organization-mcp-servers-are-gateway-only.md), [`../rbac/IMPLEMENTATION-BRIEF.md`](../rbac/IMPLEMENTATION-BRIEF.md), [`../agents.md`](../agents.md)

Goal: an Organization Owner or Admin registers a remote MCP server once, with one Organization credential, and chooses whether every Agent in the Organization may use it or only the Agents that opt in. Agents call its tools through their runtime's own MCP client, and the credential never enters a pod.

## Decisions

### Scope and credential

- **Scope is set per server.** Each Organization MCP Server has an MCP Server Scope:
  - **All Agents** applies to every Agent in the Organization, with no per-Agent opt-out. To leave an Agent out, switch the server to Selected Agents.
  - **Selected Agents** applies only to Agents with an MCP Server Attachment. Attachments survive scope changes, so switching back restores the earlier selection.
- **One Organization credential per server**: none, Bearer, or a named API-key header, plus optional secret headers. Every Agent using the server acts as that service identity. OAuth-protected servers, per-Agent credentials and Agent-owned servers are out of v1.
- **Gateway only**: there is no direct mode ([ADR](../../adr/2026-11-10-organization-mcp-servers-are-gateway-only.md)). The pod gets one per-start MCP gateway token. On every request the gateway checks:
  - that the token belongs to the Agent's running generation;
  - that the server named in the path belongs to the token's Organization and is currently available to that Agent;
  - the Tier entitlement.

  The gateway then injects the credential and forwards.
- **Streamable HTTP only**: the destination policy is the Custom API one (public HTTPS on the configured port, the address pinned, no redirects). There is no stdio and no legacy SSE. SSE was dropped in slice 2: it answers on a separate long-lived GET stream, so the probe and the gateway would each need a second, stream-correlated client, which does not count as costing little.

### Authorization and entitlement

- **Permissions**:
  - A new Organization Permission, `mcp_server.manage`, held by Owners and Admins and carried by no Agent Access Role, governs creating, editing, probing and deleting servers.
  - Reading the Organization's server list needs `organization.read` and never returns credential values. A server's URL and authentication details are returned only to `mcp_server.manage` holders, because some servers put a key in the URL's path. Audit Events record only the URL's host.
  - Attaching or detaching on an Agent needs `agent.update` and `agent.secret.manage`, through `AgentAuthorization.require_action`. Restarting also needs `agent.lifecycle.manage`.
- **Tier**: gated under the Tiers `integrations` feature (`TierFeature.INTEGRATIONS`), checked on create, enable, scope widening, attach, and at the gateway on every request. There is no new Tier feature and no server-count limit in v1. Tiers arrive with AF-437 ([aai-labs/agent-barn#361](https://github.com/aai-labs/agent-barn/pull/361)), which is not on staging yet.

### When changes take effect

- **Deleting a server Agents use is allowed.** Its attachments are deleted with it; the gateway refuses the server on the Agents' next request. The UI states the number of Agents affected before confirming.
- **Removal is live; addition waits for a restart.** These take effect at the gateway on the Agent's next request, with no restart: disable, detach, delete, a URL change, credential rotation, and tool-filter changes. A server that newly becomes available appears only after the Agent's next start, because both runtimes read MCP configuration at boot. Until then the Agent reports a pending restart. Nothing restarts Agents in bulk.

### Tools and runtime behaviour

- **Tool filter**: by default all tools are allowed. An Admin may narrow that with an include or exclude list, picked from a live `tools/list`. The gateway enforces the filter: it refuses an excluded `tools/call` and filters `tools/list` responses. Runtime-side filters only shape what the model sees.
- **No server-initiated model use or user prompts**: Hermes is configured with `sampling` and `elicitation` disabled. OpenClaw advertises neither.
- **Identifiers**: each server has an immutable, Organization-unique identifier of at most 20 characters, derived from its name. The save-time probe warns when a tool name would be truncated in OpenClaw and refuses a filter whose visible names would collide.

### OAuth sign-in and Agent credentials (slice 5)

- **Two credential owners.** An Organization MCP Server keeps its Organization credential. An Agent may have its own credential for any server it may use, and the gateway prefers it. That credential is the Agent's own token and headers for a token-based server, or an Agent sign-in for an OAuth server. An Agent's editor (`agent.update` + `agent.secret.manage`) sets or removes it; it is never shown back.
- **OAuth sign-in.**
  - Authentication `oauth` means the Agent acts as the account an Owner or Admin signed in with (the Organization sign-in), or as an Agent's own sign-in.
  - Discovery follows MCP's authorization spec: the server's 401 challenge, protected-resource metadata, then authorization-server metadata. Everything is fetched under the same public-HTTPS, pinned, no-redirect policy as the server.
  - Agent Barn registers itself through dynamic client registration where the server offers it. An Admin can instead enter a client ID and secret, for servers like GitHub that need a pre-registered app.
  - Sign-in is authorization code with PKCE (S256) and the `resource` parameter, in a popup whose signed state carries the encrypted verifier.
- **Grants stay in the gateway.** Refresh tokens are stored encrypted and never reach a pod. The gateway refreshes access tokens under a row lock and saves rotated refresh tokens. A refused refresh marks the credential "needs sign-in", and Agents are told the server needs signing in again.
- **No probe without a sign-in.** Saving an OAuth server checks discovery and registration only. Test connection and the tool picker use the Organization sign-in once there is one.

### Restricted servers and Agent MCP Servers (slice 6)

- **Restricted servers.** Owners and Admins can restrict an Organization server. Then only Owners and Admins can switch it on or off for an Agent, or set, remove or sign in an Agent's own credential for it. An open server leaves both to the Agent's Owners and Editors, as before. Editing the server itself stays with Owners and Admins either way.
- **Agent MCP Servers.** An Agent's Owners and Editors (`agent.update` + `agent.secret.manage`) can add servers for that Agent only, with their own credential, under the same probe, OAuth and gateway rules. They live in the server table with `agent_id` set and scope `agent`.
- **No Organization switch.** Nothing disallows Agent servers: an Agent that runs code could reach a server without Agent Barn, so a switch would only hide that use. Agent servers are listed only on their Agent, never on the Organization's page, matching how an Agent's own integration credentials stay off the Shared Credentials page.
- **One namespace per Agent.** An Agent server's identifier may not match an Organization server's, and an Organization server's may not match any Agent server's, since both reach the Agent's runtime side by side.

## Runtime evidence (2026-11-10)

Both pinned runtimes, Hermes v2026.8.19 (`hermes-base` 0.2.10) and OpenClaw 2026.8.2 (`openclaw-base` 0.7.7), were run against a stub of the planned gateway route. Each ran one real agent turn in which a fake model called an MCP tool. Configuration came from the real builders, with the MCP block added. Later slices may assume what follows.

### Both runtimes

- **Gateway token**: an `Authorization: Bearer <gateway token>` header is read from the environment. Hermes uses `${env:AF_GATEWAY_TOKEN_MCP}`; OpenClaw uses `${AF_GATEWAY_TOKEN_MCP}`.
- **GET and HEAD**: both runtimes accept `405` on GET. Hermes also sends HEAD and GET without a session as a preflight before `initialize`.
- **Session**: `Mcp-Session-Id` is sent on every later request, and the session ends with a DELETE.
- **Replies**: SSE-framed POST replies, including a notification before the result, are parsed.
- **Protocol version**: both negotiate protocol `2025-11-25`.
- **Tool filters**: a tool removed from `tools/list` never reaches the model. Runtime filters (Hermes `tools.exclude`, OpenClaw `toolFilter.exclude`) take raw MCP tool names.
- **Revocation**: a 403 on `tools/call` becomes an ordinary tool error and the turn continues.

### Hermes

- **Tool names**: `mcp__<identifier with "-" turned to "_">__<tool>`.
- **Tool search**: Hermes's default tool search (`tools.tool_search.enabled: auto`) hides MCP tools behind `tool_search`, `tool_describe` and `tool_call`. The `tool_search` description lists every MCP tool by name.
- **Untrusted framing**: results are wrapped in an `<untrusted_tool_result>` frame.
- **Capabilities**: elicitation (form and URL) is advertised unless it is disabled.

### OpenClaw

- **Tool names**: `<identifier>__<tool>`, truncated to 64 characters.
- **Tool list**: tools are exposed directly, and `tools.profile: full` admits them.
- **Results**: passed through unframed. The response body of a refused call is shown to the model verbatim.

### Established in slice 3

- **Both runtimes, through each image's real `start.sh`**: the generated configuration reaches the gateway with the token from the pod Secret (`runtime_tests/test_{hermes,openclaw}_mcp_servers.py`).
- **OpenClaw config on the volume**: a server listed in the saved `openclaw.json` but removed since is dropped, and an empty list starts cleanly.
- **The gateway's real HTTPS path**: run against `https://mcp.deepwiki.com/mcp` from the local gateway container. It pinned the address, verified TLS against the hostname, and relayed `initialize`, `notifications/initialized` and a `tools/call` as SSE.

### Not yet established

- **OpenClaw approval in a live agent turn**: whether OpenClaw's "tools without safety annotations will require interactive approval" warning blocks a tool call. The contract tests use OpenClaw's own MCP probe, not an agent turn, and a one-off local turn did not block.
- **Long-running calls**: the stream limits and Hermes's 180-second keep-alive `ping`.

## Current state

- Delivered:
  - **Slices 1–4**: the server list, its management API, the save-time probe, the gateway route, the runtime configuration, Agent attachments and the UI.
  - **Slice 5**: OAuth sign-in for the Organization and per Agent, with discovery, dynamic or manual client registration, a popup sign-in and gateway-side refresh. Also Agent credentials for token-based servers, and the `mcp_server_credential` table (migration `c6d45e7e2df9`).
  - **Slice 6**: restricted servers and Agent MCP Servers (migration `d3a8b61f4c20`).
- In transition: nothing.
- Next: the Tier checks, now that Tiers (AF-437, [aai-labs/agent-barn#361](https://github.com/aai-labs/agent-barn/pull/361)) is on staging; then close the epic.
- Blockers: none. The epic has no ticket yet.

## Slice order

1. Decisions, ADR, glossary and INDEX route (this log).
2. Domain and persistence: the migration, the Permission seed, the repository with the per-Agent effective-server query, Organization routes, probing and validation, Domain Events, the feature doc and the RBAC brief. The Tier checks wait for AF-437.
3. Gateway MCP route and runtime wiring: the gateway token table, the streaming route, token issuance and revocation, gateway tool filtering and limits, the Hermes and OpenClaw configuration, Agent attachment routes and apply, the pending-restart signal, and runtime contract tests in both images. It may split into gateway and runtime parts.
4. UI: the Organization settings section, the Agent configuration section and the pending-restart notice.
5. OAuth sign-in and Agent credentials.
6. Restricted servers and Agent MCP Servers.
7. Close the epic.

## Changes

### 2026-11-12 — Agent servers stay on their Agent

- **Changed**: the Organization's MCP servers page no longer lists every Agent's own servers, and `GET …/mcp-servers/agent-servers` is gone. An Agent's own servers show only on that Agent, as its own integration credentials do.
- **Removed**: the Organization switch that allowed or paused Agent servers, with its `…/mcp-servers/settings` routes, the `organization_mcp_settings` table and `organization.mcp_settings.changed`. It could not disallow anything: an Agent that runs code can reach an MCP server without Agent Barn.
- **Restyled**: the MCP screens use the shared settings components (cards, badges, buttons, inputs and notices) the other connection screens use.
- **Agent section**: no outer cards; "This Agent" then "Organization shared", with "Add server for this Agent" beside the heading. The shared servers' switches need no Edit step: Apply or Apply & Restart appears once one changed.

### 2026-11-11 — slice 6

- **Delivered**:
  - `restricted` on Organization servers, enforced on attachment changes, Agent credentials and Agent sign-ins.
  - Agent MCP Servers: create, update, delete and probe under the Agent's routes, sign-in as the Agent, and gateway and runtime use.
  - The UI: the Restricted switch, and the Agent's own servers in its MCP section.
- **Changed**:
  - Migration `d3a8b61f4c20`: `agent_id` and `restricted` on `organization_mcp_server`, and identifiers unique per Organization or per Agent.
  - `operations-v1.json` gains five operations.
  - The server events gain `restricted` and `agent_id`, and Agent servers' events have the Agent as Subject.
  - The AGENTS.md block is headed "MCP servers", since it now also names an Agent's own.

### 2026-11-11 — sign-in through a severed popup

- **Found**: signing in to ether.fi saved nothing. Its sign-in page sends `Cross-Origin-Opener-Policy: same-origin`, so the callback page had no `window.opener`, and the app read the popup as closed.
- **Changed**:
  - The callback also posts on a `BroadcastChannel`, and the app accepts only its own sign-in's state.
  - MCP sign-ins use the shared popup helper's relay (`OAuthPopupRelay` in `use-oauth-popup.ts`), which does not treat a closed-looking popup as cancelled. They wait up to the state's 10 minutes, with a Cancel button.
  - A callback error carries the state too, so the relay delivers it.

### 2026-11-11 — slice 5

- **Delivered**:
  - `oauth` authentication: discovery (RFC 9728, RFC 8414 or OpenID, plus the pre-RFC 9728 fallback), dynamic client registration or an entered client, and PKCE sign-in with `resource`.
  - The popup callback, and the Organization and Agent sign-in routes.
  - Agent credentials for token-based servers.
  - Gateway credential resolution (the Agent's first), with refresh under a row lock, rotation, a `needs_sign_in` status and access-token retirement on 401.
- **Changed**:
  - Migration `c6d45e7e2df9` (`mcp_server_credential`).
  - `operations-v1.json` gains seven operations.
  - Server and Agent reads gain sign-in and credential-source fields.
  - `organization.mcp_server.updated` gains `sign_in` and `sign_out` changes.
  - `agent.updated` gains `mcp_server_identity.<identifier>`.
- **Checked live**: discovery works against ether.fi, Notion, Linear, Sentry, Asana, Atlassian and GitHub; GitHub offers no registration, so it needs an entered client.
- **Not done**: a sign-in with a real account, which needs a person at the popup.

### 2026-11-10 — probe refusals explained

- Changed:
  - A refused or missing credential is now reported in the server's own words, from its `WWW-Authenticate` challenge's `error_description`.
  - A 400 `invalid_token` counts as a refusal instead of unavailability.
  - When the server also offers OAuth sign-in, the message says that sign-in isn't supported yet, without implying OAuth is the server's only option. GitHub, for example, accepts personal access tokens too.
  - The probe now sends a User-Agent: without one, some servers' firewalls answered 403 (seen on `https://mcp.ether.fi/mcp`).
- Follow-up: OAuth sign-in for MCP servers, with the grant kept in the gateway. It needs a decision on whose account an Organization-wide server signs in with.

### 2026-11-10 — slices 3 and 4

- **Delivered, gateway**:
  - `agent_mcp_gateway_token`, issued at each start and valid only for that generation;
  - `/gateway/v1/mcp/{identifier}`, which streams, enforces the tool filter, refuses GET, HEAD and batches, does not follow redirects, redacts the credential, and caps size, time and per-server concurrency.
- **Delivered, runtime**: the Hermes `mcp_servers` and OpenClaw `mcp.servers` blocks, the `AF_GATEWAY_TOKEN_MCP` Secret entry and the AGENTS.md block.
- **Delivered, Agent**: `GET/PUT /organizations/{organization_id}/agents/{agent_id}/mcp-servers`, with `pending_restart`.
- **Delivered, UI**: Organization settings → MCP servers and Agent configuration → MCP servers.
- **Changed**:
  - `init-openclaw.js` now replaces `mcp.servers` wholesale;
  - the OpenClaw overlay always carries `mcp.servers`;
  - `operations-v1.json` gains two operations;
  - `agent.updated` gains a `mcp_servers` field change.
- **Changed docs**: the feature doc, the RBAC brief, Domain Events, runtime and deployment, the testing guide and INDEX.
- **Follow-up**: the Tier checks, and closing the epic.

### 2026-11-10 — slice 2

- Delivered: the Organization MCP Server and MCP Server Attachment tables, `mcp_server.manage` for Owners and Admins, and `GET/POST /organizations/{organization_id}/mcp-servers`.
- Delivered: `GET/PATCH/DELETE …/{server_id}` and the two probe routes.
- Delivered: the save-time Streamable HTTP probe with OpenClaw tool-name checks, `effective_for_agent`, and the `organization.mcp_server.created|updated|deleted` Events.
- Changed: migration `f52dc88eb90b` and `operations-v1.json` (seven operations).
- Changed docs: `docs/features/mcp-servers.md`, the RBAC brief, Domain Events, Integrations and INDEX.
- Changed decisions: legacy SSE dropped, URL and authentication shown to managers only, delete cascades attachments, and the gateway token table moved to slice 3.
- Not done: the Tier checks, which wait for AF-437.
- Follow-up: slice 3.

### 2026-11-10 — slice 1

- Delivered: this log with the v1 decisions and runtime evidence, the gateway-only [ADR](../../adr/2026-11-10-organization-mcp-servers-are-gateway-only.md), three glossary terms, and the INDEX route.
- Follow-up: slice 2.
