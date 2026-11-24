import { expect, test } from "@playwright/test";

import {
  MCP_AGENT_SERVER_ID,
  MCP_OAUTH_ID,
  MCP_SERVER_ID,
  mockAgentServer,
  mockMcpServer,
  mockOAuthMcpServer,
} from "../fixtures/mcp-servers";
import { MOCK_AGENT_ID, mockAgentAllowedActions } from "../pages/data-support/agent-data-support.po";
import { McpServerDataSupport } from "../pages/data-support/mcp-server-data-support.po";
import { McpServersPage } from "../pages/mcp-servers-page.po";

test.describe("Organization MCP servers", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("an Owner tests a server, hides a tool and adds it", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openOrganization({ role: "OWNER", servers: [] });

    await ui.addButton.click();
    await ui.field("Name").fill("Deep Wiki");
    await expect(ui.dialog).toContainText("Identifier: deep-wiki");
    await ui.field("Server URL").fill("https://mcp.deepwiki.com/mcp");
    await ui.selectAuth("Bearer token");
    await ui.field("Token").fill("fixture-token");
    await ui.testConnection();
    await expect(ui.tools).toContainText("DeepWiki 4.0.2 · protocol 2025-11-25");
    await ui.tool("ask_wiki_question").uncheck();
    await ui.chooseAllAgents();
    await expect(ui.dialog).toContainText("Every Agent acts with this credential");
    await ui.submit("Add server");

    await expect(ui.dialog).toHaveCount(0);
    const probe = data.requests.find((request) => request.url.endsWith("/mcp-servers/probe"));
    expect(probe?.body).toMatchObject({ url: "https://mcp.deepwiki.com/mcp", auth: { type: "bearer", token: "fixture-token" } });
    const create = data.requests.find((request) => request.method === "POST" && request.url.endsWith("/mcp-servers"));
    expect(create?.body).toMatchObject({
      name: "Deep Wiki",
      scope: "all_agents",
      enabled: true,
      auth: { type: "bearer", token: "fixture-token" },
      tool_include: null,
      tool_exclude: ["ask_wiki_question"],
    });
    await expect(ui.list).toContainText("Deep Wiki");
  });

  test("a failed retest keeps the tools already chosen", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openOrganization({ role: "OWNER", servers: [] });

    await ui.addButton.click();
    await ui.field("Name").fill("Deep Wiki");
    await ui.field("Server URL").fill("https://mcp.deepwiki.com/mcp");
    await ui.testConnection();
    await ui.tool("ask_wiki_question").uncheck();
    // The server is briefly unreachable when the Owner tests again.
    const probeUrl = "**/mcp-servers/probe";
    await page.route(probeUrl, (route) =>
      route.fulfill({ status: 400, json: { detail: "The MCP server could not be used: it could not be reached." } }),
    );
    await ui.testConnection();
    await expect(ui.tools).toContainText("Connection failed");
    await expect(ui.tool("ask_wiki_question")).not.toBeChecked();
    await page.unroute(probeUrl);
    await ui.submit("Add server");

    await expect(ui.dialog).toHaveCount(0);
    const create = data.requests.find((request) => request.method === "POST" && request.url.endsWith("/mcp-servers"));
    expect(create?.body).toMatchObject({ tool_include: null, tool_exclude: ["ask_wiki_question"] });
  });

  test("editing keeps the saved token and secret header unless they are retyped", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openOrganization({ role: "OWNER" });

    await ui.editButton("DeepWiki").click();
    await expect(ui.field("Token")).toHaveValue("");
    await expect(ui.field("Token")).toHaveAttribute("placeholder", /Saved/);
    await ui.field("Name").fill("DeepWiki Prod");
    await ui.submit("Save changes");

    await expect(ui.dialog).toHaveCount(0);
    const update = data.requests.find((request) => request.method === "PATCH");
    expect(update?.url).toContain(MCP_SERVER_ID);
    expect(update?.body).toMatchObject({ name: "DeepWiki Prod", auth: { type: "bearer" } });
    expect(update?.body?.auth).not.toHaveProperty("token");
    expect(update?.body?.headers).toEqual([{ name: "X-Signing", secret: true }]);
    // The filter was not touched, so it is not sent and stays as saved.
    expect(update?.body).not.toHaveProperty("tool_exclude");
  });

  test("deleting says how many Agents lose the server", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openOrganization({ role: "OWNER" });

    await ui.deleteButton("DeepWiki").click();
    await expect(ui.dialog).toContainText("1 agent use it. They lose its tools immediately");
    await ui.dialog.getByRole("button", { name: "Delete server" }).click();

    // The last server gone, the list gives way to the empty state.
    await expect(page.getByText("No MCP servers yet")).toBeVisible();
    await expect(ui.list).toHaveCount(0);
    expect(data.requests.some((request) => request.method === "DELETE")).toBe(true);
  });

  test("a Member sees the servers read-only, without their URL", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openOrganization({ role: "MEMBER" });

    await expect(ui.list).toContainText("DeepWiki");
    await expect(ui.list).toContainText("All tools but 1");
    await expect(ui.list).not.toContainText(mockMcpServer.url);
    await expect(ui.addButton).toHaveCount(0);
    await expect(ui.editButton("DeepWiki")).toHaveCount(0);
  });

  test("a sign-in whose tools would collide is held back until a tool is hidden", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    const collision = `notion__${"x".repeat(56)}`;
    await data.openOrganization({ role: "OWNER", servers: [mockOAuthMcpServer], toolCollisions: [collision] });

    await ui.serverRow("Notion").getByRole("button", { name: "Sign in Notion for the organization" }).click();

    await expect(page.getByText(`several tools would share these names in OpenClaw: ${collision}`)).toBeVisible();
    await expect(ui.serverRow("Notion")).toContainText("Hide colliding tools");
    await expect(ui.serverRow("Notion")).toContainText("Agents can't use it until then");
    await expect(ui.serverRow("Notion").getByRole("button", { name: "Sign in Notion for the organization" })).toHaveCount(0);
    await ui.editButton("Notion").click();
    // Held back, but still signed in: the tools can be tested and a filter chosen.
    await expect(ui.dialog.getByRole("button", { name: "Test connection" })).toBeEnabled();
  });

  test("an Owner adds an OAuth server and signs it in for the organization", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openOrganization({ role: "OWNER", servers: [] });

    await ui.addButton.click();
    await ui.field("Name").fill("Notion");
    await ui.field("Server URL").fill("https://mcp.notion.com/mcp");
    await ui.selectAuth("OAuth sign-in");
    await expect(ui.field("Token")).toHaveCount(0);
    await expect(ui.dialog.getByRole("button", { name: "Test connection" })).toBeDisabled();
    await expect(ui.tools).toContainText("Save the server, then sign in for the organization");
    await ui.submit("Add server");
    await expect(ui.dialog).toHaveCount(0);

    const create = data.requests.find((request) => request.method === "POST" && request.url.endsWith("/mcp-servers"));
    expect(create?.body).toMatchObject({ name: "Notion", auth: { type: "oauth" } });
    await expect(ui.serverRow("Notion")).toContainText("Not signed in");

    await ui.serverRow("Notion").getByRole("button", { name: "Sign in Notion for the organization" }).click();
    await expect(ui.serverRow("Notion")).toContainText("Signed in");
    const complete = data.requests.find((request) => request.url.endsWith("/mcp-servers/sign-in/complete"));
    expect(complete?.body).toEqual({ code: "org-code", state: "signed-state" });

    await ui.serverRow("Notion").getByRole("button", { name: "Sign out Notion" }).click();
    await expect(ui.serverRow("Notion")).toContainText("Not signed in");
  });

  test("a sign-in page that severs the popup from the app still completes through the channel", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openOrganization({ role: "OWNER", servers: [mockOAuthMcpServer], callback: "channel" });

    await ui.serverRow("Notion").getByRole("button", { name: "Sign in Notion for the organization" }).click();

    await expect(ui.serverRow("Notion")).toContainText("Signed in");
    const complete = data.requests.find((request) => request.url.endsWith("/mcp-servers/sign-in/complete"));
    expect(complete?.body).toEqual({ code: "org-code", state: "signed-state" });
  });

  test("a sign-in still in progress can be cancelled", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openOrganization({ role: "OWNER", servers: [mockOAuthMcpServer], callback: "never" });

    await ui.serverRow("Notion").getByRole("button", { name: "Sign in Notion for the organization" }).click();
    await expect(ui.serverRow("Notion")).toContainText("Signing in…");
    await ui.serverRow("Notion").getByRole("button", { name: "Cancel sign-in" }).click();

    await expect(ui.serverRow("Notion")).toContainText("Sign in");
    await expect(ui.serverRow("Notion")).not.toContainText("Signing in…");
    expect(data.requests.some((request) => request.url.endsWith("/mcp-servers/sign-in/complete"))).toBe(false);
  });

  test("an Owner can use their own OAuth app for a server without automatic registration", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openOrganization({ role: "OWNER", servers: [] });

    await ui.addButton.click();
    await ui.field("Name").fill("GitHub");
    await ui.field("Server URL").fill("https://api.githubcopilot.com/mcp");
    await ui.selectAuth("OAuth sign-in");
    await ui.dialog.getByRole("checkbox", { name: "Use my own OAuth app" }).check();
    await expect(ui.dialog).toContainText("/api/v1/mcp-servers/oauth/callback");
    await ui.field("Client ID").fill("Iv1.example");
    await ui.field("Client secret (optional)").fill("app-secret");
    await ui.submit("Add server");

    const create = data.requests.find((request) => request.method === "POST" && request.url.endsWith("/mcp-servers"));
    expect(create?.body).toMatchObject({ auth: { type: "oauth", client_id: "Iv1.example", client_secret: "app-secret" } });
  });

  test("a Member sees an OAuth server's sign-in status but cannot sign it in", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openOrganization({
      role: "MEMBER",
      servers: [
        {
          ...mockOAuthMcpServer,
          url: null,
          auth_type: null,
          oauth_client_id: null,
          oauth_registered: null,
          sign_in: { status: "needs_sign_in", signed_in_at: "2026-11-10T00:00:00Z" },
        },
      ],
    });

    await expect(ui.serverRow("Notion")).toContainText("Needs sign-in again");
    await expect(ui.serverRow("Notion").getByRole("button")).toHaveCount(0);
  });

  test("an Owner restricts a server to Owners and Admins", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openOrganization({ role: "OWNER" });

    await ui.editButton("DeepWiki").click();
    await expect(ui.dialog.getByRole("switch", { name: "Restricted" })).toHaveAttribute("aria-checked", "false");
    await ui.dialog.getByRole("switch", { name: "Restricted" }).click();
    await ui.submit("Save changes");

    await expect(ui.dialog).toHaveCount(0);
    const update = data.requests.find((request) => request.method === "PATCH");
    expect(update?.body).toMatchObject({ restricted: true, scope: "selected_agents" });
    await expect(ui.serverRow("DeepWiki")).toContainText("Restricted");
  });

  test("Organization settings list only the organization's servers, with no switch for Agents' own", async ({
    page,
  }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openOrganization({ role: "OWNER" });

    // An Agent's own servers are listed on that Agent, like its own integration credentials,
    // and no switch disallows them: an Agent that runs code could reach a server without us.
    await expect(ui.list).toContainText("DeepWiki");
    await expect(page.getByText("Agents' own MCP servers")).toHaveCount(0);
    await expect(page.getByRole("switch")).toHaveCount(0);
  });
});

test.describe("Agent MCP servers", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("the Agent's sidebar links to its MCP servers", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    await data.openAgent();

    const link = page.getByRole("complementary").getByRole("link", { name: "MCP servers", exact: true });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", /section=mcp/);
  });

  test("All Agents servers are locked on and a Selected Agents server is switched per Agent", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openAgent();

    await expect(ui.agentSwitch("Linear")).toHaveAttribute("aria-checked", "true");
    // No Edit step: the switches are live, and Apply appears only once something changed.
    await expect(ui.agentSwitch("Linear")).toBeDisabled();
    await expect(ui.agentSwitch("DeepWiki")).toBeEnabled();
    await expect(ui.applyButton).toHaveCount(0);
    await ui.agentSwitch("DeepWiki").click();
    await ui.applyAgent();

    const put = data.requests.find((request) => request.method === "PUT");
    expect(put?.body).toEqual({ attached_server_ids: [MCP_SERVER_ID], restart: false });
    await expect(ui.agentSwitch("DeepWiki")).toHaveAttribute("aria-checked", "true");
  });

  test("a server the running Agent started without reads as needing a restart", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openAgent({ running: true, pendingRestart: true, linearRestartPending: true });

    await expect(ui.agentRow("Linear")).toContainText("Restart required");
    await expect(ui.agentRow("Linear")).toContainText("On — available after the Agent restarts");
    await expect(ui.agentRow("Notion")).not.toContainText("Restart required");
  });

  test("Discard puts the switches back without saving", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openAgent();

    await ui.agentSwitch("DeepWiki").click();
    await expect(ui.agentSwitch("DeepWiki")).toHaveAttribute("aria-checked", "true");
    await ui.agentSection.getByRole("button", { name: "Discard" }).click();

    await expect(ui.agentSwitch("DeepWiki")).toHaveAttribute("aria-checked", "false");
    await expect(ui.applyButton).toHaveCount(0);
    expect(data.requests.some((request) => request.method === "PUT")).toBe(false);
  });

  test("a running Agent the editor may restart applies with a restart", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openAgent({ running: true });

    await ui.agentSwitch("DeepWiki").click();
    await expect(ui.agentSection.getByRole("button", { name: "Apply & Restart" })).toBeVisible();
    await ui.applyAgent();

    const put = data.requests.find((request) => request.method === "PUT");
    expect(put?.body).toEqual({ attached_server_ids: [MCP_SERVER_ID], restart: true });
    await expect(page.getByText("Restart to apply")).toHaveCount(0);
  });

  test("a running Agent saved without restart permission shows that a restart is pending", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openAgent({
      running: true,
      actions: mockAgentAllowedActions.filter((action) => action !== "agent.lifecycle.manage"),
    });

    await ui.agentSwitch("DeepWiki").click();
    await ui.applyAgent();

    const put = data.requests.find((request) => request.method === "PUT");
    expect(put?.body).toEqual({ attached_server_ids: [MCP_SERVER_ID], restart: false });
    await expect(page.getByRole("alert").filter({ hasText: "Restart to apply" })).toBeVisible();
  });

  test("a viewer sees the servers without controls", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openAgent({ attached: true, actions: ["agent.read", "activity.read"] });

    await expect(ui.agentSwitch("DeepWiki")).toHaveAttribute("aria-checked", "true");
    await expect(ui.agentSwitch("DeepWiki")).toBeDisabled();
    await expect(ui.agentRow("DeepWiki")).toContainText("Uses the organization's credential");
    await expect(ui.agentRow("DeepWiki").getByRole("button")).toHaveCount(0);
  });

  test("an editor gives the Agent its own token for a token-based server", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openAgent();

    await expect(ui.agentRow("DeepWiki")).toContainText("Uses the organization's credential");
    await ui.agentRow("DeepWiki").getByRole("button", { name: "Use this Agent's own credential" }).click();
    await ui.field("Token").fill("agent-token");
    await ui.dialog.getByRole("button", { name: "Save credential" }).click();
    await expect(ui.dialog).toHaveCount(0);

    const put = data.requests.find((request) => request.method === "PUT" && request.url.endsWith("/credential"));
    expect(put?.url).toContain(`/mcp-servers/${MCP_SERVER_ID}/credential`);
    expect(put?.body).toEqual({ auth: { type: "bearer", token: "agent-token" }, headers: [] });
    await expect(ui.agentRow("DeepWiki")).toContainText("Uses this Agent's own credential");
  });

  test("an editor signs an OAuth server in with the Agent's own account, then goes back to the organization's", async ({
    page,
  }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openAgent();

    await expect(ui.agentRow("Notion")).toContainText("Needs a sign-in");
    await ui.agentRow("Notion").getByRole("button", { name: "Sign in with this Agent's own account" }).click();
    await expect(ui.agentRow("Notion")).toContainText("Signed in with this Agent's own account");
    const start = data.requests.find((request) => request.url.endsWith(`/mcp-servers/${MCP_OAUTH_ID}/sign-in`));
    expect(start?.method).toBe("POST");
    const complete = data.requests.find((request) => request.url.endsWith("/mcp-servers/sign-in/complete"));
    expect(complete?.body).toEqual({ code: "agent-code", state: "signed-state" });

    await ui.agentRow("Notion").getByRole("button", { name: "Use the organization's instead" }).click();
    await ui.dialog.getByRole("button", { name: "Use the organization's" }).click();
    await expect(ui.agentRow("Notion")).toContainText("Needs a sign-in");
    const remove = data.requests.find((request) => request.method === "DELETE");
    expect(remove?.url).toContain(`/mcp-servers/${MCP_OAUTH_ID}/credential`);
  });

  test("changing the Agent's own credential starts from the saved one and keeps its secrets", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openAgent({
      agentCredential: {
        auth_type: "api_key",
        auth_header_name: "X-Api-Key",
        headers: [
          { name: "X-Org", secret: false, value: "acme" },
          { name: "X-Signing", secret: true, value: null },
        ],
      },
    });

    await expect(ui.agentRow("DeepWiki")).toContainText("Uses this Agent's own credential");
    await ui.agentRow("DeepWiki").getByRole("button", { name: "Change this Agent's credential" }).click();
    await expect(ui.field("Authentication")).toContainText("API key header");
    await expect(ui.field("Header name").first()).toHaveValue("X-Api-Key");
    await expect(ui.field("API key")).toHaveAttribute("placeholder", "Saved — leave blank to keep it");
    await expect(ui.dialog.locator("#agent-mcp-header-0-name")).toHaveValue("X-Org");
    await expect(ui.dialog.locator("#agent-mcp-header-0-value")).toHaveValue("acme");
    await expect(ui.dialog.locator("#agent-mcp-header-1-name")).toHaveValue("X-Signing");
    await expect(ui.dialog.locator("#agent-mcp-header-1-value")).toHaveAttribute("placeholder", "Saved — leave blank to keep it");

    await ui.dialog.getByRole("button", { name: "Save credential" }).click();
    await expect(ui.dialog).toHaveCount(0);
    const put = data.requests.find((request) => request.method === "PUT" && request.url.endsWith("/credential"));
    expect(put?.body).toEqual({
      auth: { type: "api_key", header_name: "X-Api-Key" },
      headers: [
        { name: "X-Org", value: "acme", secret: false },
        { name: "X-Signing", secret: true },
      ],
    });
  });

  test("a restricted server is locked for an Agent editor who is not an Owner or Admin", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openAgent({ restricted: true });

    await expect(ui.agentRow("DeepWiki")).toContainText("Restricted");
    await expect(ui.agentRow("DeepWiki")).toContainText("Only organization Owners and Admins can change it");
    await expect(ui.agentRow("DeepWiki").getByRole("button", { name: "Use this Agent's own credential" })).toHaveCount(0);
    await expect(ui.agentSwitch("DeepWiki")).toBeDisabled();
  });

  test("an Owner or Admin switches a restricted server on for an Agent", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openAgent({ restricted: true, canManageRestricted: true });

    await ui.agentSwitch("DeepWiki").click();
    await ui.applyAgent();

    const put = data.requests.find((request) => request.method === "PUT");
    expect(put?.body).toEqual({ attached_server_ids: [MCP_SERVER_ID], restart: false });
  });

  test("an editor adds a server for this Agent only", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openAgent();

    await ui.addOwnServerButton.click();
    await expect(ui.dialog).toContainText("Only this Agent uses it.");
    await expect(ui.dialog.getByRole("radio", { name: /All Agents/ })).toHaveCount(0);
    await expect(ui.dialog.getByRole("switch", { name: "Restricted" })).toHaveCount(0);
    await ui.field("Name").fill("Sentry");
    await ui.field("Server URL").fill("https://mcp.sentry.dev/mcp");
    await ui.selectAuth("Bearer token");
    await ui.field("Token").fill("fixture-token");
    await ui.testConnection();
    await expect(ui.tools).toContainText("DeepWiki 4.0.2");
    await ui.submit("Add server");

    await expect(ui.dialog).toHaveCount(0);
    const probe = data.requests.find((request) => request.url.endsWith(`/agents/${MOCK_AGENT_ID}/mcp-servers/probe`));
    expect(probe?.body).toMatchObject({ url: "https://mcp.sentry.dev/mcp" });
    const create = data.requests.find(
      (request) => request.method === "POST" && request.url.endsWith(`/agents/${MOCK_AGENT_ID}/mcp-servers`),
    );
    expect(create?.body).toMatchObject({ name: "Sentry", auth: { type: "bearer", token: "fixture-token" } });
    expect(create?.body).not.toHaveProperty("scope");
    expect(create?.body).not.toHaveProperty("restricted");
    await expect(ui.ownServers).toContainText("Sentry");
  });

  test("an editor edits and deletes the Agent's own server", async ({ page }) => {
    const data = new McpServerDataSupport(page);
    const ui = new McpServersPage(page);
    await data.openAgent({ agentServers: [mockAgentServer] });

    await ui.ownServers.getByRole("button", { name: "Edit Sentry" }).click();
    await ui.field("Name").fill("Sentry Prod");
    await ui.submit("Save changes");
    await expect(ui.dialog).toHaveCount(0);
    const update = data.requests.find((request) => request.method === "PATCH");
    expect(update?.url).toContain(`/agents/${MOCK_AGENT_ID}/mcp-servers/${MCP_AGENT_SERVER_ID}`);
    expect(update?.body).toMatchObject({ name: "Sentry Prod" });

    await ui.ownServers.getByRole("button", { name: "Delete Sentry Prod" }).click();
    await ui.dialog.getByRole("button", { name: "Delete server" }).click();
    await expect(ui.ownServers).not.toContainText("Sentry Prod");
  });
});
