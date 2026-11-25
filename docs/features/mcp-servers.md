# Organization MCP Servers

## Read when

Read before changing Organization MCP Servers or Agent MCP Servers: the server list and its credential, restricted servers, OAuth sign-in and Agent credentials, MCP Server Scope and MCP Server Attachments, Agents' own servers, the save-time probe, which servers an Agent may use, the gateway's MCP route, how an Agent's runtime is configured for them, their UI, or the `mcp_server.manage` Permission. Delivery state is in the [change log](mcp-servers/CHANGELOG.md).

## Role in the system

An Organization MCP Server is a remote MCP server that an Organization registers once, with one Organization-owned credential, so that its Agents can call the server's tools. The credential is the Organization's and many Agents use it, so Agents reach the server only through the credential gateway and the credential never enters a pod ([ADR](../adr/2026-11-10-organization-mcp-servers-are-gateway-only.md)).

The pieces:

- **Organization settings → MCP servers**: Owners and Admins register servers, test them and choose their tools, and restrict them.
- **Agent configuration → MCP servers**: an Agent's editor attaches it to Selected Agents servers (Owners and Admins only, for a restricted one) and adds servers for that Agent only.
- **Agent start**: each runtime is told the gateway URL of every server the Agent may use.
- **Credential gateway**: relays each MCP request to the server with the server's credential.

## Model

### Servers

`organization_mcp_server` has one row per server, owned by its Organization and deleted with it. An **Agent MCP Server** is a row with `agent_id` set and scope `agent`: it belongs to that Agent, tied to `agent(id, organization_id)` and deleted with it, and is never shared (see [Agent MCP Servers](#agent-mcp-servers)). A database check keeps scope `agent` and `agent_id` together.

- **Identifier**: immutable and at most 20 characters. Organization servers' identifiers are unique in the Organization, and an Agent server's are unique among that Agent's. Both reach an Agent's runtime side by side, so the services also refuse an Agent server an identifier an Organization server has, and an Organization server one any Agent server has (`409`). Should both still meet, `effective_for_agent` keeps the Organization's. It is derived from the name at creation (lowercase letters and digits, other runs replaced by single hyphens) and does not change when the server is renamed. Runtimes name tools after it: OpenClaw as `<identifier>__<tool>`, cut at 64 characters, and Hermes as `mcp__<identifier with "-" turned to "_">__<tool>`.
- **Name and description**: the description is optional. Later slices show it to Agents.
- **URL**: plain public HTTPS, with no credentials, query or fragment, and an unambiguous path. These are the Custom API base URL rules (`parse_url` in `../../api/domains/custom_api/request.py`).
- **Credential**: authentication `none`, `bearer`, `api_key` (a named header carrying the key) or `oauth` (an OAuth sign-in), plus up to 32 extra headers, each ordinary or secret. It is stored as one blob encrypted with the Agent credential key, in the same shape Custom API connections use. For `oauth` the blob holds the discovered endpoints, the scope and the OAuth client, never a grant; see [OAuth sign-in](#oauth-sign-in).
- **Scope**: `all_agents` or `selected_agents` for an Organization server; new ones default to `selected_agents`. `agent` for an Agent server.
- **Restricted**: an Organization server only (a database check refuses it on an Agent server). Only Owners and Admins may switch a restricted server on or off for an Agent, or change an Agent's own credential for it; see [Restricted servers](#restricted-servers). Defaults to off.
- **Enabled**: a disabled server is kept but no Agent may use it.
- **Tool filter**: an include list or an exclude list of exact tool names, never both (a database check enforces this). At most 200 names. No filter means every tool the server offers.

### Attachments

`agent_mcp_server_attachment` has one row per Agent and Selected Agents server.

- **Same Organization**: composite foreign keys tie the row to `agent(id, organization_id)` and to `organization_mcp_server(id, organization_id)`, so an Agent cannot be attached to another Organization's server even by a direct write.
- **Deletion**: rows go with the Agent or the server.
- **Scope changes**: rows survive them, and while a server is All Agents they have no effect.

### Held credentials

`mcp_server_credential` holds credentials apart from the server row. It is tied to the server and, for an Agent's, to `agent(id, organization_id)`, and goes with either.

- **The Organization's sign-in**: one row per OAuth server with `agent_id` NULL. A token-based server keeps its Organization credential on the server row instead, so a database check refuses a static row without an Agent.
- **An Agent's own credential**: at most one row per Agent and server. `static` holds `auth` and `headers` in the server row's shape; `oauth` holds the Agent's own sign-in.
- **A grant**: the refresh token, the current access token and its expiry, encrypted. `status` is `active`; `needs_sign_in`, set when the authorization server refused a refresh; or `needs_tool_filter`, set when the sign-in's tools collide (see [OAuth sign-in](#oauth-sign-in)).
- **When rows go**:
  - A URL or OAuth client change on an OAuth server removes all of that server's rows.
  - A URL change, or a switch from OAuth to a token, on a token-based server removes its OAuth rows.

### Gateway tokens

`agent_mcp_gateway_token` holds one row per Agent, tied to `agent(id, organization_id)` and deleted with the Agent. It stores the SHA-256 of the token the Agent's current start was given and that start's integration runtime generation; each start replaces it. See [Gateway route](#gateway-route).

### Which servers an Agent may use

`McpServerRepository.effective_for_agent` returns the servers an undeleted Agent may use, from its own Organization only:

- enabled Organization servers whose scope is All Agents;
- enabled Selected Agents servers it is attached to;
- its own enabled Agent servers.

Identifiers are unique in the result.

It applies no user visibility, because its callers (Agent start and the gateway) authorize the Agent by other means.

## Management API

Base path: `/api/v1/organizations/{organization_id}/mcp-servers`.

| Operation | Permission | Notes |
| --- | --- | --- |
| `GET ""`, `GET "/{server_id}"` | `organization.read` | Every member may list and read. |
| `POST ""` | `mcp_server.manage` | Creates a server and probes it first. Returns 201. |
| `PATCH "/{server_id}"` | `mcp_server.manage` | Partial update. The identifier never changes. |
| `DELETE "/{server_id}"` | `mcp_server.manage` | Returns 204. Attachments are deleted with the server. |
| `POST "/probe"` | `mcp_server.manage` | Probes an unsaved server. Its `name` only shapes the OpenClaw names reported. |
| `POST "/{server_id}/probe"` | `mcp_server.manage` | Probes the saved server, or the saved server with an optional update body applied. Nothing is saved. |

These routes reach Organization servers only: an Agent server's id is `404` here, including for sign-in. It is reached through its Agent's routes, and no route lists every Agent's servers, as none lists every Agent's own integration credentials.

- **Status codes**: a caller from another Organization gets 403, as on every Organization route. A server outside the caller's Organization is 404. A name whose identifier is taken is 409.
- **Credentials are never returned.** Reads omit token values and secret header values.
- **Manager-only fields**: `url`, `auth_type`, `auth_header_name` and `headers` are returned only to callers holding `mcp_server.manage`. Some MCP servers put a key in the URL's path, so the URL is as sensitive as the credential. Members get those fields as null and empty.
- **Usage counts**: reads carry `attachment_count` (attachments of undeleted Agents) and `agent_count` (undeleted Agents the server reaches: every Agent for All Agents, the attached ones for Selected Agents). `agent_count` counts a disabled server's reach as if it were enabled.
- **Saved secrets on update**: a saved token carries over when the same scheme is resent without one, and for `api_key` only when the header name is also unchanged. A secret header resent without a value keeps the saved value of the same name. A submitted header list replaces the saved one. Setting either filter field replaces the whole filter.
- **Unchanged saves**: an update that changes nothing records nothing.

## Save-time probe

Creating a server connects to it once. So does an update that changes its URL, authentication, headers or tool filter. A wrong URL or key therefore fails the save instead of an Agent's first call. Renaming, rescoping, enabling or disabling, and editing the description do not connect.

`McpServerProbe` (`../../api/domains/mcp_servers/probe.py`) speaks Streamable HTTP the way the pinned runtimes do:

- the sequence is `initialize` with protocol `2025-11-25`, then `notifications/initialized`, then `tools/list` following `nextCursor` up to 10 pages;
- it ends the session with DELETE;
- it sends the User-Agent `agent-barn-mcp-probe/1`, because some servers' firewalls refuse a request without one;
- it carries `Mcp-Session-Id` and `MCP-Protocol-Version` once they are known;
- it reads JSON or SSE replies up to 1 MiB, with a 15-second timeout per request.

It applies the Custom API destination policy: every DNS answer must be public, the connection is pinned to a checked address, TLS is verified against the configured host, and redirects are refused. Legacy SSE transport is not supported.

**Failure mapping:**
- A destination the policy refuses, or an incomplete credential, is 422.
- A server that cannot be used is 400 with the reason. That covers refused credentials (401/403), unreachable, redirecting, not answering MCP, and a JSON-RPC error, whose message is redacted of the credential.
- A refused or missing credential is 400 with the server's own reason where it gave one (the `error_description` of its `WWW-Authenticate` challenge, redacted of the credential). That covers a 401 or 403, and a 400 whose challenge says `invalid_token`.
- When that challenge names `resource_metadata`, MCP's sign that the server offers an OAuth sign-in, the message adds that OAuth sign-in is not supported yet. Many such servers (GitHub, Linear, Atlassian, Supabase) also accept an API token, so without a credential it suggests adding one, and with one it reports the refusal first.

**Report:**
- **Server**: its name, version and negotiated protocol.
- **Each tool**: its OpenClaw name, whether that name is cut at 64 characters, and whether the tool filter lets Agents see it.
- **Warnings**: no tools offered, no tools visible, names OpenClaw shortens, and filter names the server does not offer.

When two visible tools would share an OpenClaw name after cutting, the probe reports it, and a save is refused (400) until the filter hides all but one of each. A signed-in OAuth server is checked the same way, with its own sign-in, when an update changes its filter or headers; before any sign-in there is nothing to connect with.

## Audit

Each create, update and delete stages one Organization-scoped Domain Event in the same transaction as the change, projected by `security_audit.projection`: `organization.mcp_server.created`, `.updated` and `.deleted`.

- **Payload contents**: the server's id, identifier, the URL's host only, scope, enabled, `restricted`, `agent_id` (an Agent server's Agent), authentication type, `changed_fields` (for an update), the number of attachments, and display names.
- **Agent servers**: their events use the same names, with the Agent as the Subject.
- **Never in the payload**: the credential and the URL's path.

## OAuth sign-in

A server with authentication `oauth` acts as an account someone signed in with: the Organization sign-in by an Owner or Admin, or an Agent's own sign-in by that Agent's editor. Implementation: `../../api/domains/mcp_servers/oauth.py`, `sign_in.py`, `broker.py`.

**Saving** an OAuth server sets the sign-in up, and nothing is probed until someone signs in.

1. **Discovery** follows MCP's authorization spec. The server's unauthenticated `initialize` must answer 401. Its challenge's `resource_metadata` (RFC 9728), or the well-known location, names the authorization server. Servers without protected-resource metadata act as their own. That server's metadata (RFC 8414, then OpenID discovery) must name the same issuer, give authorization and token endpoints, and support PKCE with S256 when it lists methods. Every endpoint must be a public HTTPS URL: the authorization endpoint above all, because the sign-in popup shares the app's origin until it navigates there, so a `javascript:` URL would run as the app. `authorize_url` checks it again, and the app opens only an HTTPS sign-in URL. A server that answers `initialize` without a sign-in is refused.
2. **Registration** uses dynamic client registration (RFC 7591) with the redirect URI `{WEB_APP_URL}/api/v1/mcp-servers/oauth/callback`. It asks for a public client where allowed, else a client with a secret. An Admin may instead enter a client ID and secret for a server without registration, such as GitHub.
3. **Scope** is the challenge's, else the resource's `scopes_supported`, unless the Admin entered one.

All of these requests follow the server's own policy: public HTTPS, a pinned address, no redirects. An edit that changes neither the URL, the client nor the scope keeps the registration and every sign-in.

**Signing in** happens in a popup:

1. **Start**: `POST …/mcp-servers/{id}/sign-in` (Organization, `mcp_server.manage`) or `POST …/agents/{agent_id}/mcp-servers/{id}/sign-in` (Agent, `agent.update` + `agent.secret.manage`) returns an authorize URL. It carries PKCE (S256), the `resource` parameter (RFC 8707) and a signed state that expires in 10 minutes. The state names the Organization, server, Agent, user and client, and carries the verifier encrypted.
2. **Callback**: the unauthenticated `GET /api/v1/mcp-servers/oauth/callback` checks only the state's signature, then posts `{type: "agentbarn-mcp-sign-in", code, state}`, or an error (with the state, when it is valid), twice.
   - **On a `BroadcastChannel`** of that name. Some authorization servers (ether.fi) send `Cross-Origin-Opener-Policy: same-origin`, which leaves the popup without an opener. The app accepts a channel message only with the state of the sign-in it started. Because such a popup also reads as closed, it keeps waiting until the state expires (10 minutes) or the person cancels.
   - **To `window.opener`** on the web app's origin, where there still is one.
3. **Complete**: `POST …/mcp-servers/sign-in/complete` with `{code, state}`.
   - It needs the user who started the sign-in (`403` otherwise), and rechecks their permissions.
   - The server's client must be unchanged (`409` otherwise).
   - It redeems the code with the verifier, then checks the server with the new access token: it probes the tools and runs the save-time collision analysis under the server's tool filter. This is the first point an OAuth server can be checked. A server that can't be probed is `400` and nothing is saved.
   - It stores the grant encrypted with its audit Event. When visible tools would share an OpenClaw name, the grant is stored as `needs_tool_filter` and the answer lists the names in `tool_collisions`. Such a grant serves Test connection and the checks of a new filter, but the gateway refuses it to Agents ("This MCP server can't be used yet: several of its tools would share a name…"). Saving a filter that passes, or signing in again once the tools pass, makes it `active`.
   - A refused or expired code is `400`, and nothing is saved.
4. **Sign out**: `DELETE …/mcp-servers/{id}/sign-in` removes the Organization's sign-in.

**Reads**: every member sees an OAuth server's `sign_in` status (`signed_in`, `needs_sign_in`, `needs_tool_filter`, `not_signed_in`). The Agent read also gives `needs_tool_filter` for the credential an Agent uses. Managers also see the client ID and whether Agent Barn registered it, never its secret.

**Test connection** on an OAuth server uses the Organization sign-in, and needs one.

## Restricted servers

A restricted Organization server keeps who may lend it to an Agent with Owners and Admins (`mcp_server.manage`), who also choose to restrict it. For a restricted server, these also need `mcp_server.manage`, on top of the Agent Permissions they always need (`403` with "This MCP server is restricted…" otherwise):

- **Attaching**: changing whether the Agent is attached to it. A save that leaves its attachment as it was does not need it, so an editor can still change other servers.
- **Agent credentials**: setting or removing an Agent's own token, and signing the Agent in. Completing a sign-in rechecks it, so restricting a server stops a sign-in already started.

Restricting a server changes no existing attachment or credential. The Agent read says which servers are `restricted`, and `can_manage_restricted` for the caller.

## Agent MCP Servers

An Agent MCP Server is added for one Agent, by the people who edit that Agent. It has an Organization server's fields except scope and `restricted`. Its credential is its own: a token on the server row, or for OAuth a sign-in held as that Agent's credential (`mcp_server_credential` with its `agent_id`). The gateway treats it like any server the Agent may use.

Base path: `/api/v1/organizations/{organization_id}/agents/{agent_id}/mcp-servers`.

| Operation | Permission | Notes |
| --- | --- | --- |
| `POST ""` | `agent.update` + `agent.secret.manage` | Creates one and probes it first, like an Organization server. Returns 201. |
| `PATCH "/{server_id}"` | `agent.update` + `agent.secret.manage` | Partial update, as for an Organization server. |
| `DELETE "/{server_id}"` | `agent.update` + `agent.secret.manage` | Returns 204. The Agent loses it at the gateway at once. |
| `POST "/probe"`, `POST "/{server_id}/probe"` | `agent.update` + `agent.secret.manage` | As for an Organization server. |
| `POST "/{server_id}/sign-in"`, `DELETE "/{server_id}/credential"` | `agent.update` + `agent.secret.manage` | Signs an OAuth Agent server in, or out. |

- **Another Agent's server** is `404` on these routes, and an Agent server is `404` on the Organization routes. `PUT "/{server_id}/credential"` refuses an Agent server (`404`): its token is edited with the server.
- **No Organization switch**: nothing lets the Organization disallow Agent servers. An Agent that runs code can reach any public MCP server with a credential of its own, so refusing the managed path would only hide that use; through the gateway its credential at least stays out of the pod and its use is audited.
- **Reads**: the Agent read lists them under `agent_servers`. Their URL and authentication shape are given only to callers with `agent.update` and `agent.secret.manage`.
- **Starting**: a new one reaches a running Agent at its next start, which `pending_restart` reports.

## Agent credentials

An Agent may have its own credential for any server in its Organization, and the gateway prefers it to the Organization's. This changes only whose identity the Agent uses: scope, attachments and `active` are unchanged.

- **Token-based servers**: `PUT …/agents/{agent_id}/mcp-servers/{id}/credential` with `{auth, headers}` in the server's shape (`none`, `bearer` or `api_key`). It is checked with a live probe like a server save. A secret left blank keeps the Agent's saved one under the same rules. An OAuth server refuses it (`400`): the Agent signs in instead.
- **OAuth servers**: the Agent sign-in above.
- **Removing**: `DELETE …/agents/{agent_id}/mcp-servers/{id}/credential` removes either kind, and the Agent goes back to the Organization's credential.
- **Permissions**: setting or removing needs `agent.update` and `agent.secret.manage`, and `mcp_server.manage` too for a [restricted server](#restricted-servers). The credential is never returned.

The Agent read gives each server's `auth_type`, `credential_source` (`agent`, `organization`, or `missing` for an OAuth server nobody signed in to), `needs_sign_in` and `has_agent_credential`. It also gives `agent_credential`, the shape of an Agent's own token-based credential so it can be edited: the authentication type, header name, and headers with non-secret values only. The token and secret header values are never returned.

**Audit**:
- An Organization sign-in or sign-out stages `organization.mcp_server.updated` with `changed_fields` `["sign_in"]` or `["sign_out"]`.
- An Agent credential change stages `agent.updated` with `field_changes.mcp_server_identity.<identifier>`, giving the previous and new source (`organization` or `agent`).
- No grant or token is ever in a payload.

## Agent attachments

Base path: `/api/v1/organizations/{organization_id}/agents/{agent_id}/mcp-servers`.

| Operation | Permission | Notes |
| --- | --- | --- |
| `GET` | `agent.read` | Every Organization server, each with `attached` (the Agent has an attachment) and `active` (the Agent may use it now), plus `pending_restart`. |
| `PUT` | `agent.update` + `agent.secret.manage`; `agent.lifecycle.manage` when `restart` is true; `mcp_server.manage` to change a restricted server's attachment | Body `{attached_server_ids, restart}`: the complete set of Selected Agents servers to attach. |

- **Visibility**: the Agent is resolved through `AgentAuthorization`, so an Agent the caller cannot see is `404` and a missing Permission is `403`.
- **Only Selected Agents servers**: an id that is not a Selected Agents server of the Agent's Organization is `400`.
- **Scope changes**: attachments to servers since switched to All Agents are left in place, so switching back restores them.
- **Saving while running**: allowed without a restart.
  - A removal takes effect at the gateway at once.
  - An addition is reported by `pending_restart` until the Agent next starts.
  - `restart: true` stops and starts the Agent under its lifecycle lock, like the Custom API apply flow.
- **Conflicts**: a lifecycle or restore operation in progress, or a managed update, is `409`.
- **Audit**: a change stages `agent.updated`, whose `field_changes.mcp_servers` holds the previous and new identifier lists.

`pending_restart` is true when a running Agent's started servers differ from the ones it would start with now. Each server in the read (and each Agent server) also carries `restart_pending`: the Agent may use it now but its running runtime started without it, so the UI shows it as "Restart required" rather than as loaded. The started servers are the identifiers its integration runtime snapshot recorded at start. Disabling, deleting or rescoping a server a running Agent started with also sets it.

## Runtime configuration

At every start, `AgentService._provision_and_start` reads `effective_for_agent` and writes the result through `../../api/domains/mcp_servers/runtime.py`.

**When the Agent may use at least one server:**

- **Gateway token**: a new random token goes into the pod Secret as `AF_GATEWAY_TOKEN_MCP`. Its SHA-256 hash and the new integration runtime generation replace the Agent's `agent_mcp_gateway_token` row.
- **Hermes**: `config.yaml` gets one `mcp_servers.<identifier>` block per server. Each has:
  - `url` set to `<credential gateway>/mcp/<identifier>`;
  - `headers.Authorization` set to `Bearer ${env:AF_GATEWAY_TOKEN_MCP}`;
  - 300-second tool and 30-second connect timeouts;
  - `sampling` and `elicitation` disabled, so a server can neither spend the Organization's model budget nor ask the Agent's user for input;
  - the tool filter as `tools.include` or `tools.exclude`.

  Hermes rewrites its config from the ConfigMap on every boot. By default it shows MCP tools to the model through its `tool_search` bridge, named `mcp__<identifier with "-" as "_">__<tool>`.
- **OpenClaw**: `mcp.servers.<identifier>` gets the same URL, `transport: "streamable-http"`, the header as `Bearer ${AF_GATEWAY_TOKEN_MCP}`, matching timeouts and `toolFilter`. OpenClaw names tools `<identifier>__<tool>`, cut at 64 characters.
- **AGENTS.md**: gets an "MCP servers" block naming each server and its description. It names no URL, token or command.
- **Snapshot**: the integration runtime records the server identifiers under `mcp_servers`.

**Always, for OpenClaw:** the overlay always carries `mcp.servers`, empty when the Agent may use none. `init-openclaw.js` replaces that path wholesale instead of deep-merging it into the `openclaw.json` kept on the volume, so a server removed since the last start is dropped.

**What never reaches the pod:** neither the ConfigMap nor the Secret holds a server's URL or credential.

## Gateway route

`/gateway/v1/mcp/{identifier}` on the credential gateway (`../../api/domains/mcp_servers/gateway.py`) accepts `POST`, `DELETE`, `GET` and `HEAD`.

**Checks, in order:**

1. **Token**: the bearer token's hash must match a token row whose generation is the Agent's current integration runtime generation. The runtime must be preparing, provisioned, ready or stopping, and the Agent must be running and undeleted. Anything else gets an opaque `403`.

   Stopping, failing, or the next start therefore revoke the token without a write. The Agent and Organization come only from the token row.
2. **Server**: the identifier is looked up among `effective_for_agent` for that Agent, so another Organization's server is never found.

   If the server is unavailable (disabled, detached, deleted, or out of scope), a request with an id gets a JSON-RPC error `-32001` reading "This MCP server is no longer available to this Agent.", and anything else gets `403` with that text. OpenClaw shows the text to the model, so it names nothing internal.
3. **Method**: `GET` and `HEAD` get `405`. The server-to-client stream is optional in Streamable HTTP, and refusing it keeps idle connections out of the gateway; both runtimes accept it.
4. **Body**: a POST body over 1 MiB is `413`, invalid JSON is `400`, and a JSON-RPC batch is `400`.
5. **Tool filter**: a `tools/call` for a tool the filter hides gets JSON-RPC error `-32602` "Tool not available" without contacting the server. The gateway enforces the filter because an Agent with a shell holds its token and could bypass a runtime-side filter.
6. **Concurrency**: more than 8 concurrent requests per server per gateway process get `503` with `Retry-After: 5`.

**Forwarding:**

- **Credential**: the pod's `Authorization` is replaced by the credential headers `McpCredentialBroker` resolves. That is the Agent's own credential, else the Organization's: the server's token and headers, or for an OAuth server the Organization sign-in's access token as `Bearer` plus the server's extra headers.
  - **Refresh**: an access token within 60 seconds of expiring is refreshed under the credential row's `FOR UPDATE` lock, and a rotated refresh token is saved in the same commit, so replicas share one current token. A server that does not rotate keeps its refresh token. A refreshable token is refreshed at least daily, whatever lifetime it states.
  - **No stated lifetime**: a token issued without `expires_in` (GitHub's OAuth tokens, which also come without a refresh token) has no expiry and is used until the server refuses it.
  - **Refused refresh**: the row is marked `needs_sign_in`, and Agents get a JSON-RPC error: "This MCP server's sign-in has expired; it needs to be signed in again."
  - **Missing sign-in**: an OAuth server nobody signed in to answers "This MCP server needs a sign-in before this Agent can use it."
  - **Refused access token**: a 401 from the server retires that access token, so the next request refreshes it.
- **Request headers passed through**: only `Mcp-Session-Id`, `MCP-Protocol-Version`, `Accept`, `Content-Type` and `Last-Event-ID`.
- **Destination**: the request is sent with the shared public-address pinning (`pin_to_public_address`). TLS is verified against the configured host, and no redirect is followed (`502`).
- **Answer**: streamed back line by line with only `Content-Type` and `Mcp-Session-Id`. Each line has the credential's values redacted: their raw bytes, and every JSON string literal that decodes to contain one, so a value the server JSON-escaped (a quote or backslash in the token, or `\u` escapes) is caught too.
- **Limits**: a stream is cut at 10 MiB or 10 minutes. Upstream connect timeout is 10 seconds and read timeout 300 seconds.
- **`tools/list`**: the answer is read whole (up to 5 MiB, else `502`; within the same 10 minutes, else `504`) and filtered in either JSON or SSE framing.

Refusals are logged with Agent, Organization and server identifier; no audit row is written per request.

## UI

- **Organization settings → MCP servers** (`../../ui/src/features/mcp-servers/components/mcp-servers-panel.tsx`, `?tab=mcp-servers`): every member sees the list. Owners and Admins add, edit and delete servers.
- **The add/edit dialog** (`mcp-server-dialog.tsx`):
  - **Fields**: URL, authentication, secret headers (blank keeps the saved value), scope with the All Agents warning, the Restricted switch, and the enabled switch. For an Agent server (opened with `agentId`) scope and Restricted are left out, and it saves through the Agent's routes.
  - **Test connection**: runs the probe and lists the tools with checkboxes, which save as an exclude list, or an include list when "Hide tools the server adds later" is on.
  - **Collisions**: OpenClaw name collisions are recomputed from the checkboxes and block saving.
- **Delete**: the confirmation states how many Agents use the server.
- **Agents' own servers**: not on this page; each Agent lists its own, as an Agent's own integration credentials are not listed with Shared Credentials.
- **Agent configuration → MCP servers** (`agent-mcp-servers-settings.tsx`, `?section=mcp`):
  - **What it shows**: All Agents servers as on, and Selected Agents servers as toggles.
  - **Saving**: no Edit step. The switches are live for whoever may change them. Once one differs from what is saved, Discard and Apply (Apply & Restart when the Agent runs and the user may restart it) appear, and Apply asks for confirmation.
  - **Pending**: a notice while `pending_restart` is true.
  - **Restricted**: a restricted server's toggle and credential controls are locked unless the caller is an Owner or Admin.
  - **Layout**: no outer cards. "This Agent" lists its own servers first, then "Organization shared" lists the Organization's, with Discard and Apply on that label's row once a switch changed. "Add server for this Agent" sits beside the section heading (`AddAgentMcpServerButton`).
  - **This Agent's own servers**: add, edit, sign in and delete them.

## Source map

| Concern | Source |
| --- | --- |
| Tables, DTOs, identifier and OpenClaw naming | `../../api/domains/mcp_servers/models.py` |
| Queries, usage counts, which servers an Agent may use, event staging | `../../api/domains/mcp_servers/repository.py` |
| Permissions, credential retention, probe on save | `../../api/domains/mcp_servers/service.py` |
| Probe and tool analysis | `../../api/domains/mcp_servers/probe.py` |
| Routes | `../../api/domains/mcp_servers/routes.py` |
| Agent attachments, the restricted gate, Agent servers and `pending_restart` | `../../api/domains/mcp_servers/agent_service.py`; sign-in's gate in `sign_in.py` |
| Runtime configuration | `../../api/domains/mcp_servers/runtime.py`, `../../api/domains/agents/service.py` (`_provision_and_start`), `../../api/domains/agents/scripts/openclaw/init-openclaw.js` |
| Gateway route | `../../api/domains/mcp_servers/gateway.py`, `../../api/gateway_app.py` |
| OAuth discovery, registration, sign-in and refresh | `../../api/domains/mcp_servers/oauth.py`, `../../api/domains/mcp_servers/sign_in.py`, `../../api/domains/mcp_servers/broker.py` |
| Held credentials | `McpServerCredential` in `../../api/domains/mcp_servers/models.py`, `../../api/migrations/versions/c6d45e7e2df9_mcp_server_credentials.py` |
| UI | `../../ui/src/features/mcp-servers/` |
| Migrations | `../../api/migrations/versions/f52dc88eb90b_organization_mcp_servers.py`, `c6d45e7e2df9_mcp_server_credentials.py`, `d3a8b61f4c20_agent_mcp_servers.py` (Agent servers, `restricted`) |
| Tests | `../../api/tests/integration/test_mcp_servers.py`, `../../api/tests/integration/test_mcp_servers_migration.py`, `../../api/tests/unit/test_mcp_server_probe.py`, `../../api/tests/integration/test_mcp_gateway.py`, `../../api/tests/integration/test_agent_mcp_servers.py`, `../../api/tests/integration/test_agent_own_mcp_servers.py`, `../../api/tests/integration/test_mcp_sign_in.py`, `../../api/tests/unit/test_mcp_oauth.py`, `../../api/runtime_tests/test_{hermes,openclaw}_mcp_servers.py`, `../../ui/tests/e2e/mcp-servers.spec.ts` |

## Change impact

- **Server schema**: a change affects the migration, DTOs, the encrypted credential shape (also read by the gateway), the audit payload, the UI schemas in `../../ui/src/features/mcp-servers/schemas.ts`, and `../../api/developer_docs/operations-v1.json` for route changes.
- **Runtime configuration**: changing the MCP blocks or `init-openclaw.js` moves the runtime configuration digest, so running Agents report `update_available`. Rerun `make test-api-runtime` for both runtimes, and after a Hermes or OpenClaw upgrade.
- **Gateway route**: it serves every Organization's Agents. Its limits and refusal texts are part of the Agent-facing contract.
- **OAuth**: changing `WEB_APP_URL` changes the redirect URI every registered client carries. Existing registrations then stop working until each OAuth server is saved again with a new client and signed in again.
- **Credential schemes**: a new authentication type must be added to both `McpAuthInput` and the Custom API `credential_headers` it reuses.
- **Identifier rule**: changing it affects the tool names in both runtimes and the probe's collision check.
- **Destination policy**: it is shared with Custom API connections, so changing it changes both.
