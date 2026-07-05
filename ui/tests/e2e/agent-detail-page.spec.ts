import { TEST_ORG_ID } from "../constants";
import { expect, test } from "@playwright/test";

import { MOCK_AGENT_ID, mockAgent, mockAssignedSkill, mockSecret, mockToolCall, mockVersionsForSlug } from "../pages/data-support/agent-data-support.po";
import { mockCustomSkill, mockPlatformSkill, MOCK_PLATFORM_SKILL_ID } from "../pages/data-support/skill-data-support.po";
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
    await dataSupportPage.users.interceptGetOrganizationsRequest();
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
    await dataSupportPage.users.interceptGetOrganizationsRequest();
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
    await page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}?tab=tool-calls`);

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
    await dataSupportPage.users.interceptGetOrganizationsRequest();
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

  test("shows Required skills section when re-pinning to template with required skills", async ({ page }) => {
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest({
      body: mockVersionsForSlug("scrum-master").map((v) => ({
        ...v,
        required_skills: [{
          id: MOCK_PLATFORM_SKILL_ID,
          name: "github",
          source: "aai_cli",
          required_providers: ["github"],
          tools_pointer: null,
          required: true,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }],
      })),
    });

    await page.getByRole("button", { name: /Scrum Master/ }).click();

    await expect(page.getByText("Required skills", { exact: true })).toBeVisible();
    await expect(page.getByText(mockPlatformSkill.name, { exact: true })).toBeVisible();
    await expect(page.getByText(/needs.*credential/)).toBeVisible();
  });

  test("Apply button is disabled when required skill credential form is incomplete", async ({ page }) => {
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest({
      body: mockVersionsForSlug("scrum-master").map((v) => ({
        ...v,
        required_skills: [{
          id: MOCK_PLATFORM_SKILL_ID,
          name: "github",
          source: "aai_cli",
          required_providers: ["github"],
          tools_pointer: null,
          required: true,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }],
      })),
    });

    await page.getByRole("button", { name: /Scrum Master/ }).click();

    await expect(page.getByRole("button", { name: "Apply template" })).toBeDisabled();
  });

  test("Apply button enables after filling required skill credentials", async ({ page }) => {
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest({
      body: mockVersionsForSlug("scrum-master").map((v) => ({
        ...v,
        required_skills: [{
          id: MOCK_PLATFORM_SKILL_ID,
          name: "github",
          source: "aai_cli",
          required_providers: ["github"],
          tools_pointer: null,
          required: true,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }],
      })),
    });

    await page.getByRole("button", { name: /Scrum Master/ }).click();

    await page.getByPlaceholder(/github_pat_/).fill("github_pat_test_token");
    await page.getByPlaceholder("owner-or-org").fill("acme");

    await expect(page.getByRole("button", { name: "Apply template" })).toBeEnabled();
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
    await dataSupportPage.users.interceptGetOrganizationsRequest();
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
    await dataSupportPage.users.interceptGetOrganizationsRequest();
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED" },
    });
    await dataSupportPage.agents.interceptGetAgentTemplateRequest();
    await dataSupportPage.skills.interceptGetSkillsRequest();

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.skillsTab().click();
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
    await agentDetailPage.skillsTab().click();

    await expect(page.getByText("Assigned")).toBeVisible();
    await expect(agentDetailPage.removeSkillButton()).toBeVisible();
  });

  test("shows available skills with source badges", async ({ page }) => {
    await expect(page.getByText("Add skills")).toBeVisible();
    await expect(page.getByText(mockPlatformSkill.name, { exact: true })).toBeVisible();
    await expect(page.getByText(mockCustomSkill.name)).toBeVisible();
    await expect(agentDetailPage.skillsSearchInput()).toBeVisible();
  });

  test("search filters available skills", async ({ page }) => {
    await agentDetailPage.skillsSearchInput().fill(mockCustomSkill.name);
    await expect(page.getByText(mockCustomSkill.name)).toBeVisible();
    await expect(page.getByText(mockPlatformSkill.name, { exact: true })).not.toBeVisible();
  });

  test("adding a skill moves it to the pending Assigned section", async ({ page }) => {
    await agentDetailPage.addSkillButton().first().click();

    await expect(page.getByText("Assigned")).toBeVisible();
    await expect(page.getByText("· Adding")).toBeVisible();
    await expect(agentDetailPage.cancelSkillButton()).toBeVisible();
    await expect(agentDetailPage.saveSkillsButton()).toBeVisible();
  });

  test("cancelling a pending add removes it from the list", async ({ page }) => {
    await agentDetailPage.addSkillButton().first().click();
    await expect(page.getByText("· Adding")).toBeVisible();

    await agentDetailPage.cancelSkillButton().click();

    await expect(page.getByText("· Adding")).not.toBeVisible();
    await expect(agentDetailPage.saveSkillsButton()).not.toBeVisible();
  });

  test("removing an assigned skill shows it struck-through with Undo", async () => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", skills: [mockAssignedSkill] },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.skillsTab().click();

    await agentDetailPage.removeSkillButton().click();

    await expect(agentDetailPage.undoSkillButton()).toBeVisible();
    await expect(agentDetailPage.saveSkillsButton()).toBeVisible();
  });

  test("undoing a removal restores the skill row", async () => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", skills: [mockAssignedSkill] },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.skillsTab().click();

    await agentDetailPage.removeSkillButton().click();
    await agentDetailPage.undoSkillButton().click();

    await expect(agentDetailPage.removeSkillButton()).toBeVisible();
    await expect(agentDetailPage.saveSkillsButton()).not.toBeVisible();
  });

  test("adding a skill with required providers shows credentials section", async ({ page }) => {
    // github skill requires "github" provider — click Add for it
    await agentDetailPage.addSkillButton().first().click();

    await expect(page.getByText("Required credentials")).toBeVisible();
    await expect(page.getByText("GitHub", { exact: true })).toBeVisible();
  });

  test("save button is disabled when required credentials are incomplete", async () => {
    await agentDetailPage.addSkillButton().first().click();

    await expect(agentDetailPage.saveSkillsButton()).toBeDisabled();
  });

  test("saving skills calls the update API", async ({ page }) => {
    await dataSupportPage.agents.interceptUpdateAgentRequest();
    await dataSupportPage.skills.interceptGetSkillsRequest({ body: [mockCustomSkill] });

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.skillsTab().click();

    await agentDetailPage.addSkillButton().last().click(); // custom skill — no required providers

    const updatePromise = page.waitForRequest(
      (req) =>
        req.url().includes(`/agents/${MOCK_AGENT_ID}`) &&
        req.method() === "PATCH",
    );
    await agentDetailPage.saveSkillsButton().click();
    await updatePromise;
  });

  test("required skill shows 'Required' badge and disabled Remove button", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", skills: [{ ...mockAssignedSkill, required: true }] },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.skillsTab().click();

    await expect(page.getByText("Required", { exact: true })).toBeVisible();
    await expect(agentDetailPage.removeSkillButton()).toBeDisabled();
  });

  test("hovering disabled Remove button for required skill shows tooltip", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", skills: [{ ...mockAssignedSkill, required: true }] },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.skillsTab().click();

    await agentDetailPage.removeSkillButton().hover();

    await expect(page.getByText("Required by template")).toBeVisible();
  });
});

test.describe("Agent Detail Page — Keys tab", () => {
  test.describe.configure({ mode: "serial" });
  let agentDetailPage: AgentDetailPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    agentDetailPage = new AgentDetailPage(page);
    dataSupportPage = new DataSupport(page);

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.users.interceptGetOrganizationsRequest();
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED" },
    });
    await dataSupportPage.agents.interceptGetAgentTemplateRequest();

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.keysTab().click();
  });

  test("shows app-level token and bot token inputs", async () => {
    await expect(agentDetailPage.appTokenInput()).toBeVisible();
    await expect(agentDetailPage.botTokenInput()).toBeVisible();
  });

  test("Save tokens button is disabled when both fields are empty", async () => {
    await expect(agentDetailPage.saveTokensButton()).toBeDisabled();
  });

  test("filling a token field enables Save tokens", async () => {
    await agentDetailPage.appTokenInput().fill("xapp-1-test");
    await expect(agentDetailPage.saveTokensButton()).toBeEnabled();
  });

  test("saving tokens calls the update API", async ({ page }) => {
    await dataSupportPage.agents.interceptUpdateAgentRequest();

    await agentDetailPage.appTokenInput().fill("xapp-1-test");

    const updatePromise = page.waitForRequest(
      (req) => req.url().includes(`/agents/${MOCK_AGENT_ID}`) && req.method() === "PATCH",
    );
    await agentDetailPage.saveTokensButton().click();
    await updatePromise;
  });

  test("shows error near Save tokens when token save fails", async ({ page }) => {
    await dataSupportPage.agents.interceptUpdateAgentRequest({
      status: 422,
      detail: "Invalid token format",
    });

    await agentDetailPage.appTokenInput().fill("bad-token");
    await agentDetailPage.saveTokensButton().click();

    await expect(page.getByText("Invalid token format")).toBeVisible();
  });

  test("shows Integrations section", async ({ page }) => {
    await expect(page.getByText("Integrations", { exact: true })).toBeVisible();
  });

  test("Save integrations is disabled when nothing is staged", async () => {
    await expect(agentDetailPage.saveIntegrationsButton()).toBeDisabled();
  });

  test("shows configured secret when agent has one", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", secrets: [mockSecret] },
    });
    await dataSupportPage.agents.interceptValidateIntegrationRequest();
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.keysTab().click();

    await expect(page.getByText("· not yet validated")).toBeVisible();
    await expect(agentDetailPage.removeCredentialButton()).toBeVisible();
  });

  test("clicking Remove shows credential as pending removal with Undo", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", secrets: [mockSecret] },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.keysTab().click();

    await agentDetailPage.removeCredentialButton().click();

    await expect(page.getByText("· will be removed")).toBeVisible();
    await expect(agentDetailPage.undoCredentialButton()).toBeVisible();
    await expect(agentDetailPage.saveIntegrationsButton()).toBeEnabled();
  });

  test("clicking Undo reverts credential to normal state", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", secrets: [mockSecret] },
    });
    await dataSupportPage.agents.interceptValidateIntegrationRequest();
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.keysTab().click();

    await agentDetailPage.removeCredentialButton().click();
    await agentDetailPage.undoCredentialButton().click();

    await expect(page.getByText("· not yet validated")).toBeVisible();
    await expect(agentDetailPage.removeCredentialButton()).toBeVisible();
    await expect(agentDetailPage.saveIntegrationsButton()).toBeDisabled();
  });

  test("when integrations save fails, credential is restored and error is shown", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", secrets: [mockSecret] },
    });
    await dataSupportPage.agents.interceptValidateIntegrationRequest();
    await dataSupportPage.agents.interceptUpdateAgentRequest({
      status: 409,
      detail: "Secret is used by a skill",
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.keysTab().click();

    await agentDetailPage.removeCredentialButton().click();
    await agentDetailPage.saveIntegrationsButton().click();

    await expect(page.getByText("Secret is used by a skill")).toBeVisible();
    await expect(page.getByText("· not yet validated")).toBeVisible();
  });

  test("error from token save does not appear in integrations section", async ({ page }) => {
    await dataSupportPage.agents.interceptUpdateAgentRequest({
      status: 500,
      detail: "Token save failed",
    });

    await agentDetailPage.appTokenInput().fill("xapp-1-test");
    await agentDetailPage.saveTokensButton().click();

    await expect(page.getByText("Token save failed")).toHaveCount(1);
    await expect(agentDetailPage.saveIntegrationsButton()).toBeDisabled();
  });
});
