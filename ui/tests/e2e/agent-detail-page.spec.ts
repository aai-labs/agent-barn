import { expect, test } from "@playwright/test";

import { MOCK_AGENT_ID, mockAgent, mockAssignedSkill, mockToolCall } from "../pages/data-support/agent-data-support.po";
import { mockCustomSkill, mockPlatformSkill } from "../pages/data-support/skill-data-support.po";
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

test.describe("Agent Detail Page — Skills tab", () => {
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
    await dataSupportPage.skills.interceptGetSkillsRequest();

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await page.getByRole("button", { name: "Skills" }).click();
  });

  test("Skills tab is clickable and shows the tab panel", async ({ page }) => {
    await expect(page.getByText("No skills assigned yet.")).toBeVisible();
  });

  test("shows assigned skills when agent has skills", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", skills: [mockAssignedSkill] },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await page.getByRole("button", { name: "Skills" }).click();

    await expect(page.getByText(mockAssignedSkill.name)).toBeVisible();
    await expect(page.getByRole("button", { name: "Remove" })).toBeVisible();
  });

  test("shows available skills grouped by Platform and Custom", async ({ page }) => {
    await expect(page.getByText("Add skills")).toBeVisible();
    await expect(page.getByText("Platform")).toBeVisible();
    await expect(page.getByText(mockPlatformSkill.name)).toBeVisible();
    await expect(page.getByText("Custom")).toBeVisible();
    await expect(page.getByText(mockCustomSkill.name)).toBeVisible();
  });

  test("adding a skill moves it to the pending Assigned section", async ({ page }) => {
    await page.getByRole("button", { name: "Add" }).first().click();

    await expect(page.getByText("Assigned")).toBeVisible();
    await expect(page.getByText("· Adding")).toBeVisible();
    await expect(page.getByRole("button", { name: "Cancel" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Save changes" })).toBeVisible();
  });

  test("cancelling a pending add removes it from the list", async ({ page }) => {
    await page.getByRole("button", { name: "Add" }).first().click();
    await expect(page.getByText("· Adding")).toBeVisible();

    await page.getByRole("button", { name: "Cancel" }).click();

    await expect(page.getByText("· Adding")).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Save changes" })).not.toBeVisible();
  });

  test("removing an assigned skill shows it struck-through with Undo", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", skills: [mockAssignedSkill] },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await page.getByRole("button", { name: "Skills" }).click();

    await page.getByRole("button", { name: "Remove" }).click();

    await expect(page.getByRole("button", { name: "Undo" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Save changes" })).toBeVisible();
  });

  test("undoing a removal restores the skill row", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", skills: [mockAssignedSkill] },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await page.getByRole("button", { name: "Skills" }).click();

    await page.getByRole("button", { name: "Remove" }).click();
    await page.getByRole("button", { name: "Undo" }).click();

    await expect(page.getByRole("button", { name: "Remove" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Save changes" })).not.toBeVisible();
  });

  test("adding a skill with required providers shows credentials section", async ({ page }) => {
    // github skill requires "github" provider — click Add for it
    await page.getByRole("button", { name: "Add" }).first().click();

    await expect(page.getByText("Required credentials")).toBeVisible();
    await expect(page.getByText("GitHub")).toBeVisible();
  });

  test("save button is disabled when required credentials are incomplete", async ({ page }) => {
    await page.getByRole("button", { name: "Add" }).first().click();

    await expect(page.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  test("saving skills calls the update API", async ({ page }) => {
    await dataSupportPage.agents.interceptUpdateAgentRequest();

    await page.getByRole("button", { name: "Add" }).last().click(); // custom skill — no required providers

    const updatePromise = page.waitForRequest(
      (req) =>
        req.url().includes(`/agents/${MOCK_AGENT_ID}`) &&
        req.method() === "PATCH",
    );
    await page.getByRole("button", { name: "Save changes" }).click();
    await updatePromise;
  });
});
