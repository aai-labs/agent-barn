import { expect, test } from "@playwright/test";

import { MOCK_AGENT_ID, mockAgent, mockToolCall } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { AgentDetailPage } from "../pages/agent-detail-page.po";

test.describe("Agent Detail Page", () => {
  test.describe.configure({ mode: "serial" });
  let agentDetailPage: AgentDetailPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    agentDetailPage = new AgentDetailPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.agents.interceptGetAgentRequest();
    await dataSupportPage.agents.interceptGetAgentTemplateRequest();

    await agentDetailPage.goto(MOCK_AGENT_ID);
  });

  test("should load agent detail page", async () => {
    await expect(agentDetailPage.agentName("Maya")).toBeVisible();
  });

  test("shows model name in header", async ({ page }) => {
    await expect(page.getByText("litellm/gpt-5-mini")).toBeVisible();
  });

  test("shows error state when agent fails to load", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      status: 404,
      detail: "Agent not found",
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(page.getByText("We couldn't load this agent")).toBeVisible();
    await expect(page.getByText("Agent not found")).toBeVisible();
  });

  test("should open the config drawer", async () => {
    await agentDetailPage.configureButton().click();

    await expect(agentDetailPage.configDrawerHeading()).toBeVisible();
  });

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  test("should close the config drawer", async ({ page }) => {
    await agentDetailPage.configureButton().click();
    await expect(agentDetailPage.configDrawerHeading()).toBeVisible();

    await agentDetailPage.configDrawerCloseButton().click();
    await expect(agentDetailPage.configDrawerHeading()).not.toBeVisible();
  });

  test("shows Pause button when agent is RUNNING", async ({ page }) => {
    await expect(page.getByRole("button", { name: /pause/i })).toBeVisible();
  });

  test("shows Start button when agent is STOPPED", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED" },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(page.getByRole("button", { name: /start/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /pause/i })).not.toBeVisible();
  });

  test("Pause button stops agent and updates status", async ({ page }) => {
    await dataSupportPage.agents.interceptStopAgentRequest();

    await page.getByRole("button", { name: /pause/i }).click();
    await expect(page.getByRole("button", { name: /start/i })).toBeVisible();
  });

  test("Start button starts agent and updates status", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED" },
    });
    await dataSupportPage.agents.interceptStartAgentRequest();
    await agentDetailPage.goto(MOCK_AGENT_ID);

    await page.getByRole("button", { name: /start/i }).click();
    await expect(page.getByRole("button", { name: /pause/i })).toBeVisible();
  });

});

test.describe("Agent Detail Page — Tool calls tab", () => {
  test.describe.configure({ mode: "serial" });
  let agentDetailPage: AgentDetailPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    agentDetailPage = new AgentDetailPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.agents.interceptGetAgentRequest();
    await dataSupportPage.agents.interceptGetAgentTemplateRequest();
    await dataSupportPage.agents.interceptGetToolCallsRequest();

    await agentDetailPage.goto(MOCK_AGENT_ID);
  });

  test("clicking the tab switches to tool calls view", async ({ page }) => {
    await agentDetailPage.toolCallsTab().click();

    await expect(page).toHaveURL(/tab=tool-calls/);
    await expect(page.getByRole("columnheader", { name: /tool/i })).toBeVisible();
  });

  test("renders tool calls returned by the API", async () => {
    await agentDetailPage.toolCallsTab().click();

    const row = agentDetailPage.toolCallRow("read");
    await expect(row).toBeVisible();
    await expect(row.getByText("Success")).toBeVisible();
    await expect(row.getByText("1.0 s")).toBeVisible();
  });

  test("shows empty state when there are no tool calls", async ({ page }) => {
    await dataSupportPage.agents.interceptGetToolCallsRequest({
      body: { page: 1, page_size: 20, total: 0, items: [] },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.toolCallsTab().click();

    await expect(page.getByText("No tool calls yet")).toBeVisible();
  });

  test("expanding a row reveals arguments JSON", async ({ page }) => {
    await agentDetailPage.toolCallsTab().click();

    await agentDetailPage.toolCallRow("read").click();

    await expect(page.getByText("Arguments")).toBeVisible();
    await expect(page.getByText(/config\.yaml/)).toBeVisible();
  });

  test("filtering by tool name shows only matching calls", async ({ page }) => {
    await dataSupportPage.agents.interceptGetToolCallsRequest({
      body: { page: 1, page_size: 20, total: 0, items: [] },
    });

    await agentDetailPage.toolCallsTab().click();
    await page.getByPlaceholder(/filter by tool name/i).fill("bash");

    await expect(page.getByText("No tool calls match your filters")).toBeVisible();
  });

  test("direct navigation to ?tab=tool-calls lands on the correct tab", async ({ page }) => {
    await page.goto(`/dashboard/agents/${MOCK_AGENT_ID}?tab=tool-calls`);

    await expect(page.getByRole("columnheader", { name: /tool/i })).toBeVisible();
    await expect(agentDetailPage.toolCallRow("read")).toBeVisible();
  });

  test("status badge renders for PENDING and ERROR tool calls", async () => {
    const pendingCall = { ...mockToolCall, id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", tool_name: "bash", status: "PENDING", result: null, completed_at: null, duration_ms: null };
    const errorCall = { ...mockToolCall, id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", tool_name: "write", status: "ERROR" };

    await dataSupportPage.agents.interceptGetToolCallsRequest({
      body: { page: 1, page_size: 20, total: 2, items: [pendingCall, errorCall] },
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.toolCallsTab().click();

    await expect(agentDetailPage.toolCallRow("bash").getByText("Pending")).toBeVisible();
    await expect(agentDetailPage.toolCallRow("write").getByText("Error")).toBeVisible();
  });
});

test.describe("Agent Detail Page — Template tab (re-pin)", () => {
  test.describe.configure({ mode: "serial" });
  let agentDetailPage: AgentDetailPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    agentDetailPage = new AgentDetailPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    // Stopped agent so the re-pin controls are enabled.
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED" },
    });
    await dataSupportPage.agents.interceptGetAgentTemplateRequest();
    await dataSupportPage.agents.interceptGetTemplatesRequest();
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest();
    await dataSupportPage.agents.interceptUpdateAgentRequest();

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
  });

  test("re-pins the agent to a browsed template + version", async ({ page }) => {
    // Pick a different lineage, choose v1, and apply.
    await page.getByRole("button", { name: /Scrum Master/ }).click();
    await page.getByLabel("Version").click();
    await page.getByRole("menuitemradio", { name: "v1" }).click();

    const patchPromise = page.waitForRequest(
      (req) =>
        req.url().includes(`/api/v1/agents/${MOCK_AGENT_ID}`) &&
        req.method() === "PATCH",
    );
    await page.getByRole("button", { name: "Apply template" }).click();
    const body = (await patchPromise).postDataJSON() as Record<string, unknown>;

    expect(body.template_slug).toBe("scrum-master");
    expect(body.template_version).toBe(1);
    // No per-agent markdown is ever sent.
    expect(body.soul_md).toBeUndefined();
  });
});

test.describe("Agent Detail Page — Channels tab", () => {
  test.describe.configure({ mode: "serial" });
  let agentDetailPage: AgentDetailPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    agentDetailPage = new AgentDetailPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED" },
    });
    await dataSupportPage.agents.interceptGetAgentTemplateRequest();
    await dataSupportPage.agents.interceptSlackChannelsRequest();
    await dataSupportPage.agents.interceptSlackUsersRequest();
    await dataSupportPage.agents.interceptUpdateAgentRequest();

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.channelsTab().click();
  });

  test("shows group and DM policy dropdowns with the agent's current values", async () => {
    await expect(agentDetailPage.groupPolicySelect()).toHaveValue("allowlist");
    await expect(agentDetailPage.dmPolicySelect()).toHaveValue("off");
  });


  test("focusing the channel search shows mocked channels in the dropdown", async ({
    page,
  }) => {
    await agentDetailPage.groupPolicySelect().selectOption("allowlist");
    await agentDetailPage.channelSearchInput().focus();

    await expect(page.getByRole("button", { name: /#general/ })).toBeVisible();
    await expect(
      page.getByRole("button", { name: /#engineering/ }),
    ).toBeVisible();
  });
});
