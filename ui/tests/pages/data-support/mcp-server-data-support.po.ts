import type { Page } from "@playwright/test";

import { TEST_ORG_ID } from "../../constants";
import {
  MCP_OAUTH_ID,
  MCP_SERVER_ID,
  agentMcpServers,
  membershipContext,
  mockMcpServer,
  mockAgentServer,
  mockMcpServerForMember,
  mockProbe,
} from "../../fixtures/mcp-servers";
import { MOCK_AGENT_ID, mockAgent, mockAgentAllowedActions } from "./agent-data-support.po";
import { DataSupport } from "./data-support.po";

type Recorded = { method: string; url: string; body: Record<string, unknown> | null };

const CALLBACK = "**/api/v1/mcp-servers/oauth/callback*";

/**
 * How the stand-in callback page answers:
 * - `opener`: posts to `window.opener`, as after most authorization servers;
 * - `channel`: has no opener (an authorization server's Cross-Origin-Opener-Policy severed
 *   it) and posts only on the BroadcastChannel, then closes;
 * - `never`: posts nothing, as when the person is still signing in.
 */
export type SignInCallbackMode = "opener" | "channel" | "never";

/** Stands in for the authorization server redirecting the popup back to our callback page. */
async function interceptSignInCallback(page: Page, mode: SignInCallbackMode = "opener") {
  await page.context().route(`${AUTHORIZATION_SERVER}/**`, async (route) => {
    const url = new URL(route.request().url());
    const callback = `${url.searchParams.get("back")}/api/v1/mcp-servers/oauth/callback?code=${url.searchParams.get("code")}&state=${url.searchParams.get("state")}`;
    await route.fulfill({
      status: 200,
      contentType: "text/html",
      body: `<script>window.location.replace(${JSON.stringify(callback)});</script>`,
    });
  });
  await page.context().route(CALLBACK, async (route) => {
    const url = new URL(route.request().url());
    const message = JSON.stringify({
      type: "agentbarn-mcp-sign-in",
      code: url.searchParams.get("code"),
      state: url.searchParams.get("state"),
    });
    const script = {
      opener: `window.opener.postMessage(${message}, window.location.origin); window.close();`,
      channel: `var channel = new BroadcastChannel("agentbarn-mcp-sign-in"); channel.postMessage(${message}); channel.close(); window.close();`,
      never: "",
    }[mode];
    await route.fulfill({ status: 200, contentType: "text/html", body: `<script>${script}</script>` });
  });
}

// A stand-in authorization server on HTTPS, the only scheme the app sends a popup to. Its
// sign-in page redirects straight back to the callback on the app's origin.
const AUTHORIZATION_SERVER = "https://auth.mcp.test";

function authorizeUrl(requestUrl: string, code: string) {
  const back = encodeURIComponent(new URL(requestUrl).origin);
  return { authorize_url: `${AUTHORIZATION_SERVER}/authorize?code=${code}&state=signed-state&back=${back}` };
}

/** Request interception for Organization MCP Servers and an Agent's attachments. */
export class McpServerDataSupport {
  readonly requests: Recorded[] = [];

  constructor(private page: Page) {}

  private record(route: { request: () => { method: () => string; url: () => string; postData: () => string | null; postDataJSON: () => unknown } }) {
    const request = route.request();
    this.requests.push({
      method: request.method(),
      url: request.url(),
      body: request.postData() ? (request.postDataJSON() as Record<string, unknown>) : null,
    });
  }

  /** Organization settings, as an Owner/Admin (`manager`) or a Member. */
  async openOrganization({
    role,
    servers,
    callback = "opener",
    toolCollisions = [],
  }: {
    role: "OWNER" | "MEMBER";
    servers?: Record<string, unknown>[];
    callback?: SignInCallbackMode;
    // OpenClaw names the signed-in account's tools would share: the sign-in is held back.
    toolCollisions?: string[];
  }) {
    const data = new DataSupport(this.page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({ userContext: membershipContext(role) });
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptAgentSettings();
    let list = servers ?? [role === "MEMBER" ? mockMcpServerForMember : mockMcpServer];
    let signingIn: string | null = null;
    const setSignIn = (serverId: string, status: string) => {
      list = list.map((server) =>
        server.id === serverId ? { ...server, sign_in: { status, signed_in_at: "2026-11-11T00:00:00Z" } } : server,
      );
    };
    await interceptSignInCallback(this.page, callback);
    await this.page.route(`**/api/v1/organizations/${TEST_ORG_ID}/mcp-servers**`, async (route) => {
      const request = route.request();
      if (request.method() === "GET") return route.fulfill({ json: list });
      this.record(route);
      const body = request.postData() ? (request.postDataJSON() as Record<string, unknown>) : {};
      const path = new URL(request.url()).pathname;
      if (path.endsWith("/sign-in/complete")) {
        if (signingIn) setSignIn(signingIn, toolCollisions.length ? "needs_tool_filter" : "signed_in");
        return route.fulfill({ json: { mcp_server_id: signingIn, agent_id: null, tool_collisions: toolCollisions } });
      }
      if (path.endsWith("/sign-in")) {
        const serverId = path.split("/").at(-2) ?? "";
        if (request.method() === "DELETE") {
          setSignIn(serverId, "not_signed_in");
          return route.fulfill({ status: 204 });
        }
        signingIn = serverId;
        return route.fulfill({ json: authorizeUrl(request.url(), "org-code") });
      }
      if (request.url().endsWith("/probe")) return route.fulfill({ json: mockProbe });
      if (request.method() === "DELETE") {
        list = list.filter((server) => !request.url().endsWith(String(server.id)));
        return route.fulfill({ status: 204 });
      }
      const auth = (body.auth ?? {}) as Record<string, unknown>;
      const saved = {
        ...mockMcpServer,
        id: request.method() === "POST" ? "6a6a6a6a-3333-4333-8333-333333333333" : mockMcpServer.id,
        identifier: String(body.name ?? mockMcpServer.name).toLowerCase().replace(/[^a-z0-9]+/g, "-"),
        ...body,
        auth_type: auth.type ?? mockMcpServer.auth_type,
        auth_header_name: auth.header_name ?? null,
        headers: [],
        ...(auth.type === "oauth"
          ? { oauth_client_id: auth.client_id ?? "registered-client", oauth_registered: !auth.client_id, sign_in: { status: "not_signed_in", signed_in_at: null } }
          : {}),
        attachment_count: 0,
        agent_count: 0,
      };
      delete (saved as Record<string, unknown>).auth;
      list = [...list.filter((server) => server.id !== saved.id), saved];
      return route.fulfill({ status: request.method() === "POST" ? 201 : 200, json: saved });
    });
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/settings?tab=mcp-servers`);
  }

  /** The Agent's configuration page at its MCP servers section. */
  async openAgent({
    running = false,
    attached = false,
    pendingRestart = false,
    actions = mockAgentAllowedActions,
    agentCredential,
    restricted = false,
    canManageRestricted = false,
    linearRestartPending = false,
    notionHeldForToolFilter = false,
    agentServers = [],
  }: {
    running?: boolean;
    attached?: boolean;
    pendingRestart?: boolean;
    actions?: string[];
    // DeepWiki's saved Agent credential, as the API reads it back.
    agentCredential?: Record<string, unknown>;
    // DeepWiki restricted to Owners and Admins, and whether the viewer is one.
    restricted?: boolean;
    canManageRestricted?: boolean;
    linearRestartPending?: boolean;
    // Notion signed in with the Agent's own account, held back for colliding tool names.
    notionHeldForToolFilter?: boolean;
    agentServers?: Record<string, unknown>[];
  } = {}) {
    const data = new DataSupport(this.page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.agents.interceptGetAgentConfigurationRequest();
    await data.agents.interceptGetAgentHealthRequest();
    await data.organizations.interceptGetOrganizationLlmBudget({ organizationId: TEST_ORG_ID });
    await data.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: running ? "RUNNING" : "STOPPED", allowed_actions: actions },
    });
    const shape = { restricted, canManageRestricted, linearRestartPending };
    let current = agentMcpServers({ attached, pendingRestart, agentServers, ...shape });
    let signingIn: string | null = null;
    const setSource = (serverId: string, own: boolean, credential: Record<string, unknown> | null = null) => {
      current = {
        ...current,
        servers: current.servers.map((server) =>
          server.id !== serverId
            ? server
            : {
                ...server,
                has_agent_credential: own,
                credential_source: own ? "agent" : server.auth_type === "oauth" ? "missing" : "organization",
                needs_sign_in: !own && server.auth_type === "oauth",
                // A completed sign-in passed the tool check; none here is held back.
                needs_tool_filter: false,
                agent_credential: credential,
              },
        ),
      };
    };
    if (agentCredential) setSource(MCP_SERVER_ID, true, agentCredential);
    if (notionHeldForToolFilter) {
      current = {
        ...current,
        servers: current.servers.map((server) =>
          server.id === MCP_OAUTH_ID
            ? { ...server, has_agent_credential: true, credential_source: "agent", needs_sign_in: false, needs_tool_filter: true }
            : server,
        ),
      };
    }
    await interceptSignInCallback(this.page);
    await this.page.route(`**/api/v1/organizations/*/mcp-servers/sign-in/complete`, async (route) => {
      this.record(route);
      if (signingIn) setSource(signingIn, true);
      return route.fulfill({ json: { mcp_server_id: signingIn, agent_id: MOCK_AGENT_ID } });
    });
    await this.page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/mcp-servers/*/*`, async (route) => {
      this.record(route);
      const request = route.request();
      const parts = new URL(request.url()).pathname.split("/");
      const serverId = parts.at(-2) ?? "";
      if (parts.at(-1) === "sign-in") {
        signingIn = serverId;
        return route.fulfill({ json: authorizeUrl(request.url(), "agent-code") });
      }
      if (request.method() === "DELETE") {
        setSource(serverId, false);
        return route.fulfill({ status: 204 });
      }
      // Read back like the API: no token, and secret header values withheld.
      const body = request.postDataJSON() as {
        auth: { type: string; header_name?: string };
        headers: { name: string; value?: string; secret: boolean }[];
      };
      setSource(serverId, true, {
        auth_type: body.auth.type,
        auth_header_name: body.auth.header_name ?? null,
        headers: body.headers.map((header) => ({
          name: header.name,
          secret: header.secret,
          value: header.secret ? null : (header.value ?? ""),
        })),
      });
      return route.fulfill({ json: current });
    });
    // The Agent's own servers: probing, changing and deleting one.
    await this.page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/mcp-servers/*`, async (route) => {
      this.record(route);
      const request = route.request();
      if (request.url().endsWith("/probe")) return route.fulfill({ json: mockProbe });
      const serverId = new URL(request.url()).pathname.split("/").at(-1);
      if (request.method() === "DELETE") {
        current = { ...current, agent_servers: current.agent_servers.filter((server) => server.id !== serverId) };
        return route.fulfill({ status: 204 });
      }
      const body = request.postDataJSON() as Record<string, unknown>;
      const saved = { ...current.agent_servers.find((server) => server.id === serverId), ...body };
      delete (saved as Record<string, unknown>).auth;
      current = {
        ...current,
        agent_servers: current.agent_servers.map((server) => (server.id === serverId ? saved : server)),
      };
      return route.fulfill({ json: saved });
    });
    await this.page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/mcp-servers`, async (route) => {
      if (route.request().method() === "GET") return route.fulfill({ json: current });
      this.record(route);
      if (route.request().method() === "POST") {
        const body = route.request().postDataJSON() as Record<string, unknown>;
        const auth = (body.auth ?? {}) as Record<string, unknown>;
        const saved = {
          ...mockAgentServer,
          id: "6a6a6a6a-6666-4666-8666-666666666666",
          identifier: String(body.name).toLowerCase().replace(/[^a-z0-9]+/g, "-"),
          ...body,
          auth_type: auth.type ?? "none",
        };
        delete (saved as Record<string, unknown>).auth;
        current = { ...current, agent_servers: [...current.agent_servers, saved] };
        return route.fulfill({ status: 201, json: saved });
      }
      const body = route.request().postDataJSON() as { attached_server_ids: string[]; restart: boolean };
      const next = { ...agentMcpServers({ attached: body.attached_server_ids.length > 0, agentServers: current.agent_servers, ...shape }), servers: current.servers.map((server) =>
        server.scope === "selected_agents"
          ? { ...server, attached: body.attached_server_ids.includes(server.id), active: body.attached_server_ids.includes(server.id) }
          : server,
      ) };
      current = { ...next, pending_restart: running && !body.restart && body.attached_server_ids.length > 0 };
      return route.fulfill({ json: current });
    });
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/configuration?section=mcp`);
  }
}
