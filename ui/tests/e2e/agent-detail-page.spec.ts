import { TEST_ORG_ID } from "../constants";
import { expect, test } from "@playwright/test";

import {
  MOCK_AGENT_ID,
  MOCK_ORG_ID,
  mockAgent,
  mockAgentAllowedActions,
  mockAgentConfiguration,
  mockAssignedSkill,
  mockSecret,
  mockTemplates,
  mockToolCall,
  mockVersionsForKey,
} from "../pages/data-support/agent-data-support.po";
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
    await dataSupportPage.agents.interceptGetAgentHealthRequest();
    await dataSupportPage.agents.interceptGetConversationChannelsRequest();
    await dataSupportPage.agents.interceptGetTemplatesRequest();
    await dataSupportPage.agents.interceptGetAgentConfigurationRequest();
    await dataSupportPage.agents.interceptGetModelsRequest();

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

  test("opens the canonical configuration page", async ({ page }) => {
    await agentDetailPage.configureButton().click();

    await expect(agentDetailPage.configDrawerHeading()).toBeVisible();
    await expect(page.getByRole("button", { name: "Template selection", exact: true })).toBeVisible();
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
    await dataSupportPage.agents.interceptGetAgentHealthRequest();
    await dataSupportPage.agents.interceptGetConversationChannelsRequest();

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

test.describe("Agent Detail Page — running template selection", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("enables Apply & Restart when switching from the active platform version to its organization fork", async ({ page }) => {
    const dataSupportPage = new DataSupport(page);
    const platformTemplate = mockTemplates[0];
    const organizationFork = {
      ...platformTemplate,
      id: "55555555-5555-4555-8555-555555555559",
      organization_id: MOCK_ORG_ID,
      template_source: "custom",
      forked_from_platform_template_id: platformTemplate.id,
      updated_at: "2026-05-15T09:14:00Z",
    };
    const active = {
      ...platformTemplate,
      agent_id: MOCK_AGENT_ID,
      description: null,
      source_type: "platform",
      source_template_key: "general-purpose",
      source_template_version: 1,
      source_platform_template_id: null,
      source_agent_template_id: null,
      created_by_user_id: null,
      author: null,
      state: "active",
      pin_type: "shared",
      template_source: "pre-defined",
    };

    await dataSupportPage.auth.interceptRefreshRequest();
    await dataSupportPage.users.interceptGetUserContextRequest();
    await dataSupportPage.users.interceptGetOrganizationsRequest();
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        status: "RUNNING",
        template_key: "general-purpose",
        template_version: 1,
        allowed_actions: mockAgentAllowedActions,
      },
    });
    await dataSupportPage.agents.interceptGetAgentConfigurationRequest({
      body: { ...mockAgentConfiguration, active },
    });
    await dataSupportPage.agents.interceptGetTemplatesRequest({
      body: {
        page: 1,
        page_size: 100,
        total: 2,
        items: [platformTemplate, organizationFork],
      },
    });
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest({
      body: [platformTemplate, organizationFork],
    });

    await page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/configuration`);
    await page.getByRole("button", { name: "Template selection", exact: true }).click();
    await page.getByRole("combobox", { name: "Template version" }).click();
    await page.getByRole("option", { name: /General Purpose.*v1.*Organization fork/ }).click();

    await expect(page.getByRole("button", { name: "Apply & Restart", exact: true })).toBeEnabled();
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
    await dataSupportPage.agents.interceptGetAgentConfigurationRequest();
    await dataSupportPage.agents.interceptSelectAgentTemplateRequest();
    await dataSupportPage.agents.interceptGetConversationChannelsRequest();
    await dataSupportPage.agents.interceptGetModelsRequest();

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await page.getByRole("button", { name: "Template selection", exact: true }).click();
  });

  test("re-pins the agent to a browsed template + version", async ({ page }) => {
    // Pick a different lineage/version from the searchable selector.
    await page.getByRole("combobox", { name: "Template version" }).click();
    await page.getByRole("option", { name: /Scrum Master.*v1/ }).click();

    const selectPromise = page.waitForRequest(
      (req) =>
        req.url().includes(`/agents/${MOCK_AGENT_ID}/configuration/select`) &&
        req.method() === "POST",
    );
    await page.getByRole("button", { name: /^Apply$/i }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Apply", exact: true })
      .click();
    const body = (await selectPromise).postDataJSON() as Record<string, unknown>;

    expect(body.template_key).toBe("scrum-master");
    expect(body.template_version).toBe(1);
    // No per-agent markdown is ever sent.
    expect(body.soul_md).toBeUndefined();
  });

  test("enables Apply when switching from an organization fork to its platform source", async ({ page }) => {
    const duplicateQueryWarnings: string[] = [];
    page.on("console", (message) => {
      if (message.text().includes("Duplicate Queries found")) {
        duplicateQueryWarnings.push(message.text());
      }
    });

    const platformTemplate = mockTemplates[0];
    const organizationFork = {
      ...platformTemplate,
      id: "55555555-5555-4555-8555-555555555559",
      organization_id: MOCK_ORG_ID,
      template_source: "custom",
      forked_from_platform_template_id: platformTemplate.id,
      updated_at: "2026-05-15T09:14:00Z",
    };
    const active = {
      ...mockAgentConfiguration.active,
      id: organizationFork.id,
      template_key: "general-purpose",
      template_name: "General Purpose",
      template_source: "custom",
      source_type: "organization",
      source_template_key: "general-purpose",
      source_template_version: 1,
      source_platform_template_id: platformTemplate.id,
      source_agent_template_id: organizationFork.id,
    };

    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", template_key: "general-purpose", template_version: 1 },
    });
    await dataSupportPage.agents.interceptGetAgentConfigurationRequest({
      body: { ...mockAgentConfiguration, active },
    });
    await dataSupportPage.agents.interceptGetTemplatesRequest({
      body: {
        page: 1,
        page_size: 50,
        total: 2,
        items: [platformTemplate, organizationFork],
      },
    });
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest({
      body: [platformTemplate, organizationFork],
    });

    await page.reload();
    await page.getByRole("button", { name: "Template selection", exact: true }).click();
    await page.getByRole("combobox", { name: "Template version" }).click();
    await page.getByRole("option", { name: /General Purpose.*v1.*Built-in platform/ }).click();

    expect(duplicateQueryWarnings).toHaveLength(0);
    await expect(page.getByRole("button", { name: "Apply", exact: true })).toBeEnabled();
  });

  test("shows Required skills section when re-pinning to template with required skills", async ({ page }) => {
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest({
      body: mockVersionsForKey("scrum-master").map((v) => ({
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

    await page.reload();
    await page.getByRole("button", { name: "Template selection", exact: true }).click();
    await page.getByRole("combobox", { name: "Template version" }).click();
    await page.getByRole("option", { name: /Scrum Master.*v2/ }).click();

    await expect(page.getByText("Required skills", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(mockPlatformSkill.name, { exact: true })).toBeVisible();
    await expect(page.getByTitle(/Providers: github/)).toBeVisible();
  });

  test("Apply is disabled when required skills are missing", async ({ page }) => {
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest({
      body: mockVersionsForKey("scrum-master").map((v) => ({
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

    await page.reload();
    await page.getByRole("button", { name: "Template selection", exact: true }).click();
    await page.getByRole("combobox", { name: "Template version" }).click();
    await page.getByRole("option", { name: /Scrum Master.*v2/ }).click();

    await expect(page.getByRole("button", { name: /^Apply$/i })).toBeDisabled();
  });

  test("Apply remains disabled until required skills are assigned", async ({ page }) => {
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest({
      body: mockVersionsForKey("scrum-master").map((v) => ({
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

    await page.reload();
    await page.getByRole("button", { name: "Template selection", exact: true }).click();
    await page.getByRole("combobox", { name: "Template version" }).click();
    await page.getByRole("option", { name: /Scrum Master.*v2/ }).click();

    await expect(page.getByRole("button", { name: /^Apply$/i })).toBeDisabled();
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
    await dataSupportPage.agents.interceptGetConversationChannelsRequest();
    await dataSupportPage.agents.interceptGetTemplatesRequest();
    await dataSupportPage.agents.interceptGetAgentConfigurationRequest();
    await dataSupportPage.agents.interceptGetModelsRequest();

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.channelsTab().click();
    await agentDetailPage.editButton().click();
  });

  test("shows group and DM policy dropdowns with the agent's current values", async () => {
    await expect(agentDetailPage.groupPolicySelect()).toHaveValue("allowlist");
    await expect(agentDetailPage.dmPolicySelect()).toHaveValue("off");
  });

  test("uses the card footer for cancel and apply actions", async ({ page }) => {
    const footer = page.locator('section[aria-label="Channels & endpoint"] footer');

    await expect(footer.getByRole("button", { name: "Cancel", exact: true })).toBeVisible();
    await expect(footer.getByRole("button", { name: "Apply", exact: true })).toBeDisabled();

    await agentDetailPage.groupPolicySelect().selectOption("open");
    await expect(footer.getByRole("button", { name: "Apply", exact: true })).toBeEnabled();

    await footer.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.getByRole("button", { name: "Edit", exact: true })).toBeVisible();
  });

  test("shows Discord routing and write-only token controls", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        status: "STOPPED",
        platform: "discord",
        slack_config: null,
        discord_config: {
          guild_ids: ["guild-1"],
          allowed_channel_ids: ["channel-1"],
          allowed_user_ids: ["user-1"],
          allowed_role_ids: ["role-1"],
          allow_all_users: false,
          home_channel_id: "channel-1",
          require_mention: true,
          group_policy: "allowlist",
        },
      },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.channelsTab().click();
    await agentDetailPage.editButton().click();

    await expect(page.getByRole("textbox", { name: "Allowed server IDs" })).toHaveValue("guild-1");
    await expect(page.getByRole("textbox", { name: "Allowed role IDs" })).toHaveValue("role-1");

    await page.getByRole("button", { name: "Keys & integrations", exact: true }).click();
    await agentDetailPage.editButton().click();
    await expect(page.getByPlaceholder("Leave blank to keep existing token")).toBeVisible();
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
    await dataSupportPage.skills.interceptGetAgentSkillsRequest();
    await dataSupportPage.agents.interceptGetConversationChannelsRequest();
    await dataSupportPage.agents.interceptGetTemplatesRequest();
    await dataSupportPage.agents.interceptGetAgentConfigurationRequest();
    await dataSupportPage.agents.interceptGetModelsRequest();
    await dataSupportPage.agents.interceptStartAgentRequest();

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.skillsTab().click();
    await agentDetailPage.editButton().click();
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
    await agentDetailPage.editButton().click();

    await expect(page.getByText("Assigned", { exact: true })).toBeVisible();
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

    await expect(page.getByText("Assigned", { exact: true })).toBeVisible();
    await expect(page.getByText("· Adding")).toBeVisible();
    await expect(agentDetailPage.cancelSkillButton()).toBeVisible();
    await expect(agentDetailPage.saveSkillsButton()).toBeVisible();
  });

  test("cancelling a pending add removes it from the list", async ({ page }) => {
    await agentDetailPage.addSkillButton().first().click();
    await expect(page.getByText("· Adding")).toBeVisible();

    await agentDetailPage.cancelSkillButton().click();

    await expect(page.getByText("· Adding")).not.toBeVisible();
    await expect(agentDetailPage.saveSkillsButton()).toBeDisabled();
  });

  test("removing an assigned skill shows it struck-through with Undo", async () => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", skills: [mockAssignedSkill] },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.skillsTab().click();
    await agentDetailPage.editButton().click();

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
    await agentDetailPage.editButton().click();

    await agentDetailPage.removeSkillButton().click();
    await agentDetailPage.undoSkillButton().click();

    await expect(agentDetailPage.removeSkillButton()).toBeVisible();
    await expect(agentDetailPage.saveSkillsButton()).toBeDisabled();
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
    await dataSupportPage.skills.interceptGetAgentSkillsRequest({ body: [mockCustomSkill] });

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.skillsTab().click();
    await agentDetailPage.editButton().click();

    await agentDetailPage.addSkillButton().last().click(); // custom skill — no required providers

    const updatePromise = page.waitForRequest(
      (req) =>
        req.url().includes(`/agents/${MOCK_AGENT_ID}`) &&
        req.method() === "PATCH",
    );
    await agentDetailPage.saveSkillsButton().click();
    await agentDetailPage.applyAndRestartConfirmationButton().click();
    await updatePromise;
  });

  test("required skill shows 'Required' badge and disabled Remove button", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", skills: [{ ...mockAssignedSkill, required: true }] },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.skillsTab().click();
    await agentDetailPage.editButton().click();

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
    await agentDetailPage.editButton().click();

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
    await dataSupportPage.agents.interceptGetConversationChannelsRequest();
    await dataSupportPage.agents.interceptGetTemplatesRequest();
    await dataSupportPage.agents.interceptGetAgentConfigurationRequest();
    await dataSupportPage.agents.interceptGetModelsRequest();
    await dataSupportPage.agents.interceptStartAgentRequest();

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.keysTab().click();
    await agentDetailPage.editButton().click();
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
    await agentDetailPage.applyAndRestartConfirmationButton().click();
    await updatePromise;
  });

  test("shows error near Save tokens when token save fails", async ({ page }) => {
    await dataSupportPage.agents.interceptUpdateAgentRequest({
      status: 422,
      detail: "Invalid token format",
    });

    await agentDetailPage.appTokenInput().fill("bad-token");
    await agentDetailPage.saveTokensButton().click();
    await agentDetailPage.applyAndRestartConfirmationButton().click();

    await expect(
      page.locator('section[aria-label="Keys & integrations"]').getByText("Invalid token format"),
    ).toBeVisible();
  });

  test("shows Integrations section", async ({ page }) => {
    await expect(page.getByText("Integration credentials", { exact: true })).toBeVisible();
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
    await agentDetailPage.editButton().click();

    await expect(page.getByText("Value hidden")).toBeVisible();
    await expect(agentDetailPage.removeCredentialButton()).toBeVisible();
  });

  test("clicking Remove shows credential as pending removal with Undo", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", secrets: [mockSecret] },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.keysTab().click();
    await agentDetailPage.editButton().click();

    await agentDetailPage.removeCredentialButton().click();

    await expect(page.getByText("Will be removed")).toBeVisible();
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
    await agentDetailPage.editButton().click();

    await agentDetailPage.removeCredentialButton().click();
    await agentDetailPage.undoCredentialButton().click();

    await expect(page.getByText("Value hidden")).toBeVisible();
    await expect(agentDetailPage.removeCredentialButton()).toBeVisible();
    await expect(agentDetailPage.saveIntegrationsButton()).toBeDisabled();
  });

  test("when integrations save fails, the pending removal and error remain visible", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", secrets: [mockSecret] },
    });
    await dataSupportPage.agents.interceptValidateIntegrationRequest();
    await dataSupportPage.agents.interceptUpdateAgentRequest({
      status: 409,
      detail: "Secret is used by a skill",
    });
    await dataSupportPage.agents.interceptStartAgentRequest({
      body: { ...mockAgent, status: "RUNNING", secrets: [mockSecret] },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.keysTab().click();
    await agentDetailPage.editButton().click();

    await agentDetailPage.removeCredentialButton().click();
    await agentDetailPage.saveIntegrationsButton().click();
    await agentDetailPage.applyAndRestartConfirmationButton().click();

    await expect(
      page.locator('section[aria-label="Keys & integrations"]').getByText("Secret is used by a skill"),
    ).toBeVisible();
    await expect(page.getByText("Will be removed")).toBeVisible();
  });

  test("error from token save does not appear in integrations section", async ({ page }) => {
    await dataSupportPage.agents.interceptUpdateAgentRequest({
      status: 500,
      detail: "Token save failed",
    });

    await agentDetailPage.appTokenInput().fill("xapp-1-test");
    await agentDetailPage.saveTokensButton().click();
    await agentDetailPage.applyAndRestartConfirmationButton().click();

    await expect(page.getByText("Token save failed")).toHaveCount(1);
    await expect(agentDetailPage.saveIntegrationsButton()).toBeEnabled();
  });
});

test.describe("Agent Detail Page — Personality tab (approval mode)", () => {
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
      body: { ...mockAgent, status: "STOPPED", agent_type: "hermes" },
    });
    await dataSupportPage.agents.interceptGetAgentTemplateRequest();
    await dataSupportPage.agents.interceptGetTemplatesRequest();
    await dataSupportPage.agents.interceptGetTemplateVersionsRequest();
    await dataSupportPage.agents.interceptGetAgentConfigurationRequest();
    await dataSupportPage.agents.interceptUpdateAgentRequest();
    await dataSupportPage.agents.interceptGetConversationChannelsRequest();
    await dataSupportPage.agents.interceptGetModelsRequest();
    await dataSupportPage.agents.interceptStartAgentRequest();

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await page.getByRole("button", { name: "Profile", exact: true }).click();
    await agentDetailPage.editButton().click();
  });

  test("shows command approval select defaulting to auto from agent data", async ({ page }) => {
    await expect(page.getByRole("combobox", { name: "Command approval" })).toContainText(/Auto/);
  });

  test("saving name & model sends approval_mode in the PATCH request", async ({ page }) => {
    await page.getByRole("combobox", { name: "Command approval" }).click();
    await page.getByRole("option", { name: /Off/ }).click();

    const patchPromise = page.waitForRequest(
      (req) =>
        req.url().includes(`/agents/${MOCK_AGENT_ID}`) &&
        req.method() === "PATCH",
    );
    await page.getByRole("button", { name: /^Apply$/i }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Apply", exact: true })
      .click();
    const body = (await patchPromise).postDataJSON() as Record<string, unknown>;

    expect(body.approval_mode).toBe("off");
  });
});
