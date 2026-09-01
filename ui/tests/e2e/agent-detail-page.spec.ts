import { expect, test, type Locator } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import {
  COMMUNICATION_DELIVERY_ID,
  SAFE_ERROR_DETAILS,
  SAFE_PROVIDER_ERROR,
} from "../fixtures/communication-connections";
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
import { CommunicationConnectionDetailPage } from "../pages/communication-connection-detail-page.po";

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

  test("shows configured messaging platform icons", async ({ page }) => {
    await expect(page.getByAltText("Slack")).toBeVisible();
    await expect(page.getByAltText("Discord")).toBeVisible();
  });

  test("shows model name in header", async ({ page }) => {
    await expect(page.getByText("litellm/gpt-5-mini")).toBeVisible();
  });

  test("guides an unreachable Agent to messaging setup", async ({ page }) => {
    await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/connections`, async (route) => {
      if (route.request().method() !== "GET") {
        await route.fallback();
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);

    await expect(page.getByText("Messaging setup", { exact: true })).toBeVisible();
    await expect(page.getByText("Make Maya reachable", { exact: true })).toBeVisible();
    await expect(page.getByText("Not connected", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Add connection" })).toHaveAttribute(
      "href",
      /configuration\?section=channels&connect=true/,
    );
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
  let connectionDetailPage: CommunicationConnectionDetailPage;
  let dataSupportPage: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    agentDetailPage = new AgentDetailPage(page);
    connectionDetailPage = new CommunicationConnectionDetailPage(page);
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
    await dataSupportPage.communicationConnections.interceptChannelsRequests({ agentId: MOCK_AGENT_ID });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.channelsTab().click();
  });

  test("lists Connection identity and health independently of the Agent runtime", async () => {
    await expect(agentDetailPage.connectionIdentity("validation-skipped")).toBeVisible();
    await expect(agentDetailPage.connectionProviderStatus("Connected")).toBeVisible();
  });

  test("shows a redacted provider error at full width", async () => {
    const providerError = agentDetailPage.providerErrorAlert();
    const errorMessage = agentDetailPage.providerErrorMessage();
    await expect(errorMessage).toHaveText(SAFE_PROVIDER_ERROR);
    expect(await errorMessage.evaluate((element) => getComputedStyle(element).getPropertyValue("-webkit-line-clamp"))).toBe("none");
    expect(await providerError.evaluate((element) => getComputedStyle(element).maxWidth)).toBe("none");
    const widths = await providerError.evaluate((element) => ({
      alert: element.getBoundingClientRect().width,
      content: element.parentElement?.getBoundingClientRect().width ?? 0,
    }));
    expect(widths.alert).toBeCloseTo(widths.content, 0);
  });

  test("shows delivery activity, lets an operator copy an error, and confirms a reconnect request", async ({ context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    // Delivery transitions are the primary activity surface. Connection
    // failures are explained inline from the diagnostics read model.
    const initialDeliveryRequest = connectionDetailPage.waitForJournalRequest("delivery");
    const journalRequests = connectionDetailPage.startJournalRequestCapture();
    await agentDetailPage.connectionDetailsLink().click();
    const deliveryRequest = await initialDeliveryRequest;
    journalRequests.stop();
    expect(journalRequests.urls.some((url) => url.includes("kind=connection"))).toBe(false);
    const deliveryWindow = new URL(deliveryRequest.url()).searchParams;
    expect(deliveryWindow.get("since")).toBe("2025-12-31T00:00:00Z");
    expect(deliveryWindow.get("until")).toBe("2026-01-01T00:00:00Z");

    await expect(connectionDetailPage.summaryMetric("Provider connectivity")).toBeVisible();
    await expect(connectionDetailPage.summaryMetric("End-to-end delivery")).toBeVisible();
    // AF-273 acceptance criteria: the diagnostics view exposes a pipeline
    // summary and the latest transitions (delivery and connection-scoped) from
    // the summary read model — no separate kind=connection journal request.
    await expect(connectionDetailPage.pipelineSummary()).toBeVisible();
    await expect(connectionDetailPage.pipelineStage("providerObserved")).toContainText("2");
    await expect(connectionDetailPage.pipelineStage("providerDelivered")).toContainText("2");
    await expect(connectionDetailPage.latestTransitionsPanel()).toBeVisible();
    await expect(connectionDetailPage.latestTransitionRow("provider_delivered")).toContainText("Provider Delivered");
    await expect(connectionDetailPage.latestTransitionRow("connection_connected")).toContainText("Connection");
    await expect(connectionDetailPage.summaryMetric("Health signals")).toBeVisible();
    await expect(connectionDetailPage.summaryMetric("Connection health")).toBeVisible();
    await expect(connectionDetailPage.summaryMetric("Recent incidents")).toBeVisible();
    await expect(connectionDetailPage.connectionHealthSummary()).toBeVisible();
    await expect(connectionDetailPage.summaryMetric("Consecutive delivery failures")).toBeVisible();
    await expect(connectionDetailPage.summaryMetric("Delivery success rate")).toBeVisible();
    await expect(connectionDetailPage.summaryMetric("Recent failures")).toBeVisible();
    await expect(connectionDetailPage.recentFailureCards()).toHaveCount(1);
    const failureCard = connectionDetailPage.recentFailureCard();
    await expect(failureCard).toContainText("×2");
    await expect(failureCard).toContainText(SAFE_PROVIDER_ERROR);
    await expect(connectionDetailPage.failureDetailsToggle()).toHaveText("Show details");
    await connectionDetailPage.failureDetailsToggle().click();
    await expect(failureCard).toContainText("Error details");
    await expect(failureCard).toContainText("provider_error");
    await expect(failureCard).toContainText(COMMUNICATION_DELIVERY_ID);
    await expect(failureCard).toContainText("HTTP status");
    await expect(failureCard).toContainText(String(SAFE_ERROR_DETAILS.http_status));
    await expect(failureCard).toContainText(SAFE_ERROR_DETAILS.provider_code);
    await expect(failureCard).toContainText("Retryable");
    await expect(failureCard).toContainText("Yes");
    await expect(failureCard).toContainText(SAFE_ERROR_DETAILS.request_id);
    await expect(failureCard).not.toContainText("Occurrences");
    await expect(connectionDetailPage.failureDetailsToggle()).toHaveText("Hide details");
    await expect(connectionDetailPage.deliveryEventCount(1)).toBeVisible();
    const deliveryRow = connectionDetailPage.deliveryTransitionRow(/provider delivered/i);
    await expect(deliveryRow).toContainText("Outbound");
    await expect(deliveryRow).toContainText(/dead lettered/i);
    await deliveryRow.click();
    await expect(connectionDetailPage.deliveryTiming()).toBeVisible();
    await expect(connectionDetailPage.waitBeforeAttempt()).toBeVisible();
    const copyError = connectionDetailPage.copyErrorButton("provider delivered");
    await expect(copyError).toBeVisible();
    await copyError.click();
    await expect(copyError).toHaveText("Copied");
    expect(await connectionDetailPage.readClipboard()).toBe("provider_error: " + SAFE_PROVIDER_ERROR);

    const failedOnlyRequest = connectionDetailPage.waitForFailedOnlyRequest();
    await connectionDetailPage.failedOnlyCheckbox().check();
    await failedOnlyRequest;

    await connectionDetailPage.failedOnlyCheckbox().uncheck();

    const reconnect = connectionDetailPage.waitForReconnectRequest();
    await connectionDetailPage.reconnectButton().click();
    await expect(connectionDetailPage.reconnectDialog()).toBeVisible();
    await connectionDetailPage.confirmReconnectButton().click();
    await reconnect;
  });

  test("drills down into a Delivery's full lifecycle from a transition row", async () => {
    await agentDetailPage.connectionDetailsLink().click();
    await connectionDetailPage.deliveryTransitionRow(/provider delivered/i).click();

    const lifecycleRequest = connectionDetailPage.waitForDeliveryLifecycleRequest(COMMUNICATION_DELIVERY_ID);
    const lifecyclePageTwoRequest = connectionDetailPage.waitForDeliveryLifecyclePageRequest(COMMUNICATION_DELIVERY_ID, 2);
    await connectionDetailPage.deliveryTimelineButton().click();
    await lifecycleRequest;
    await lifecyclePageTwoRequest;

    await expect(connectionDetailPage.summaryMetric("Delivery timeline")).toBeVisible();
    await expect(connectionDetailPage.timelineStage("reply queued")).toBeVisible();
    await expect(connectionDetailPage.timelineStage("provider delivered")).toBeVisible();
    await expect(connectionDetailPage.timelineStage("recovered")).toBeVisible();
  });

  test("edits Connection name and plugin settings without resending credentials", async () => {
    await agentDetailPage.editConnectionButton("Customer Discord").click();
    await agentDetailPage.connectionNameInput().fill("Renamed Discord");
    // Array settings are chip inputs: clear the existing chip ("Community" is the
    // directory label for guild-one), then add the new ID.
    await agentDetailPage.removeArraySettingChip("Community").click();
    await agentDetailPage.connectionSettingsInput("Guild IDs").fill("guild-updated");
    const update = agentDetailPage.waitForConnectionMutation("PATCH");
    await agentDetailPage.saveConnectionButton().click();
    expect((await update).postDataJSON()).toEqual({
      revision: 3,
      display_name: "Renamed Discord",
      settings: { guild_ids: ["guild-updated"] },
    });
  });

  test("shows provider setup requirements before connecting", async ({ page }) => {
    await agentDetailPage.addConnectionButton().click();
    await agentDetailPage.selectPlatformButton("Slack").click();

    const hint = agentDetailPage.setupHint(/Create credentials/);
    await expect(hint).toBeVisible();
    await expect(page.getByRole("heading", { name: "Create a Slack app" })).toBeVisible();
    await expect(page.getByText("connections:write", { exact: true })).toBeVisible();
    await expect(page.getByText("xapp-", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Slack app management" })).toHaveAttribute("href", "https://api.slack.com/apps");
    await expect(page.getByRole("button", { name: "Copy Slack manifest" })).toBeVisible();

    await agentDetailPage.selectPlatformButton("Discord").click();
    const discordHint = agentDetailPage.setupHint(/Invite the bot/);
    await expect(discordHint).toBeVisible();
    await expect(page.getByRole("heading", { name: "Create a bot" })).toBeVisible();
    await expect(page.getByText("Read Message History", { exact: true })).toBeVisible();

    await agentDetailPage.selectPlatformButton("Telegram").click();
    const telegramHint = agentDetailPage.setupHint(/@BotFather/);
    await expect(telegramHint).toBeVisible();
    await expect(telegramHint).toContainText("getUpdates");
    await expect(telegramHint).toContainText("/setprivacy");
    await expect(telegramHint).toContainText("webhook");
  });

  test("browses the Slack workspace to fill channel IDs from names", async ({ page }) => {
    await agentDetailPage.addConnectionButton().click();
    await agentDetailPage.selectPlatformButton("Slack").click();

    // Browsing needs both tokens, so it stays disabled until the credentials are typed.
    const browse = agentDetailPage.browseDirectoryButton("Allowed channels");
    await expect(browse).toBeDisabled();
    await expect(page.getByText("Add the bot token and app-level token above to browse.").first()).toBeVisible();

    await agentDetailPage.credentialInput("Bot token").fill("xoxb-token");
    await agentDetailPage.credentialInput("App-level token").fill("xapp-token");

    const preview = page.waitForRequest(
      (request) => request.method() === "POST" && request.url().includes("/connection-directory-preview"),
    );
    await browse.click();
    expect((await preview).postDataJSON()).toMatchObject({
      platform_key: "slack",
      credentials: { bot_token: "xoxb-token", app_token: "xapp-token" },
    });

    // The picker searches names, but only the underlying platform IDs are stored.
    await agentDetailPage.directoryPickerSearch("Search channels…").fill("ops");
    await agentDetailPage.directoryPickerOption(/#ops/).click();
    await agentDetailPage.directoryPickerConfirmButton().click();
    await expect(agentDetailPage.directoryPicker()).toBeHidden();
    await expect(page.getByRole("button", { name: "Remove #ops", exact: true })).toBeVisible();

    const create = agentDetailPage.waitForConnectionMutation("POST");
    await agentDetailPage.connectPlatformButton("Slack").click();
    expect((await create).postDataJSON()).toEqual({
      platform_key: "slack",
      display_name: "Slack",
      enabled: true,
      settings: { channel_ids: ["C1"] },
      credentials: { bot_token: "xoxb-token", app_token: "xapp-token" },
    });
  });

  test("puts credentials above the Connection name in the add form", async ({ page }) => {
    await agentDetailPage.addConnectionButton().click();
    await agentDetailPage.selectPlatformButton("Slack").click();

    const topOf = async (locator: Locator) => (await locator.boundingBox())?.y ?? Number.NaN;
    const credentials = await topOf(page.getByText("Credentials", { exact: true }));
    const connectionName = await topOf(page.getByPlaceholder("Slack connection"));
    const connectionSettings = await topOf(page.getByText("Connection settings", { exact: true }));

    expect(credentials).toBeLessThan(connectionName);
    expect(connectionName).toBeLessThan(connectionSettings);
  });

  test("creates another same-platform Connection from the plugin schema", async () => {
    await agentDetailPage.addConnectionButton().click();
    await agentDetailPage.selectPlatformButton("Discord").click();
    await agentDetailPage.connectionSettingsInput("Guild IDs").fill("guild-two, guild-three");
    const botToken = agentDetailPage.credentialInput("Bot token");
    await botToken.fill("token-two");
    await expect(botToken).toHaveAttribute("type", "password");
    await agentDetailPage.credentialVisibilityButton("Bot token", false).click();
    await expect(botToken).toHaveAttribute("type", "text");
    await agentDetailPage.credentialVisibilityButton("Bot token", true).click();
    await expect(botToken).toHaveAttribute("type", "password");
    const create = agentDetailPage.waitForConnectionMutation("POST");
    await agentDetailPage.connectPlatformButton("Discord").click();
    expect((await create).postDataJSON()).toEqual({
      platform_key: "discord",
      display_name: "Discord",
      enabled: true,
      settings: { guild_ids: ["guild-two", "guild-three"] },
      credentials: { bot_token: "token-two" },
    });
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
  });

  test("Skills tab is clickable and shows the tab panel", async () => {
    await expect(agentDetailPage.skillsSearchInput()).toBeVisible();
  });

  test("shows assigned skills when agent has skills", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", skills: [mockAssignedSkill] },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.skillsTab().click();

    const assignedSkillLink = page.locator(
      `a[href="/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/skills/${mockAssignedSkill.id}"]`,
    );
    await expect(assignedSkillLink.getByText("In use", { exact: true })).toBeVisible();
    await expect(agentDetailPage.removeSkillButton()).toBeVisible();
  });

  test("opens an assigned skill detail page from its card", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", skills: [mockAssignedSkill] },
    });
    await dataSupportPage.skills.interceptGetSkillFilesRequest({
      skillId: mockAssignedSkill.id,
      scope: "agent",
      agentId: MOCK_AGENT_ID,
      skill: {
        ...mockCustomSkill,
        id: mockAssignedSkill.id,
        name: mockAssignedSkill.name,
        organizationId: MOCK_ORG_ID,
        isAssignedToAgent: true,
      },
      files: [{ path: "SKILL.md", content: "# GitHub" }],
    });
    await dataSupportPage.skills.interceptGetSkillVersionsRequest({
      skillId: mockAssignedSkill.id,
      scope: "agent",
      agentId: MOCK_AGENT_ID,
    });

    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.skillsTab().click();

    const assignedSkillLink = page.locator(
      `a[href="/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/skills/${mockAssignedSkill.id}"]`,
    );
    await expect(assignedSkillLink).toBeVisible();
    await assignedSkillLink.click();

    await expect(page).toHaveURL(
      new RegExp(`/agents/${MOCK_AGENT_ID}/skills/${mockAssignedSkill.id}$`),
    );
    await expect(page.getByRole("heading", { name: mockAssignedSkill.name })).toBeVisible();

    const backLink = page.getByRole("link", { name: "Agent skills" });
    await expect(backLink).toHaveAttribute(
      "href",
      `/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/configuration?section=skills`,
    );
  });

  test("shows available skills with source badges", async ({ page }) => {
    await expect(agentDetailPage.skillsSearchInput()).toBeVisible();
    const platformSkillCard = page.getByRole("link", { name: /github/ }).first();
    await expect(platformSkillCard).toBeVisible();
    await expect(platformSkillCard.getByText("Built in")).toBeVisible();
    await expect(page.getByRole("link", { name: /my-tool/ }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Add", exact: true })).toHaveCount(4);
    await expect(
      page.getByRole("link", { name: `View details for ${mockPlatformSkill.name}` }),
    ).toHaveCount(0);
    await expect(agentDetailPage.skillsSearchInput()).toBeVisible();
  });

  test("opens an available skill detail page and returns to Agent skills", async ({ page }) => {
    await page.route(
      `**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/skills/${MOCK_PLATFORM_SKILL_ID}/files`,
      async (route) => {
        if (route.request().method() !== "GET") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ...mockPlatformSkill,
            files: [{ path: "github_skill.md", content: "# GitHub" }],
          }),
        });
      },
    );
    await page.route(
      `**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/skills/${MOCK_PLATFORM_SKILL_ID}/versions`,
      async (route) => {
        if (route.request().method() !== "GET") {
          await route.fallback();
          return;
        }
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              version: 1,
              created_by: null,
              created_at: "2026-01-01T00:00:00Z",
              is_pinned_by_agent: false,
            },
          ]),
        });
      },
    );

    await page.getByRole("link", { name: /github/ }).click();

    await expect(page).toHaveURL(
      new RegExp(`/agents/${MOCK_AGENT_ID}/skills/${MOCK_PLATFORM_SKILL_ID}$`),
    );
    await expect(page.getByRole("heading", { name: mockPlatformSkill.name })).toBeVisible();

    const backLink = page.getByRole("link", { name: "Agent skills" });
    await expect(backLink).toHaveAttribute(
      "href",
      `/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/configuration?section=skills`,
    );
    await backLink.click();
    await expect(page).toHaveURL(
      new RegExp(`/agents/${MOCK_AGENT_ID}/configuration\\?section=skills$`),
    );
    await expect(agentDetailPage.skillsSearchInput()).toBeVisible();
  });

  test("search filters available skills", async ({ page }) => {
    await agentDetailPage.skillsSearchInput().fill(mockCustomSkill.name);
    await expect(page.getByRole("link", { name: /my-tool/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /github/ })).not.toBeVisible();
  });

  test("adding a skill marks its card In use while pending", async ({ page }) => {
    await agentDetailPage.addSkillButton().first().click();

    const pendingCard = page.locator("article").filter({ hasText: "· Adding" });
    await expect(pendingCard.getByText("In use", { exact: true })).toBeVisible();
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

  test("removing an assigned skill shows it struck-through with Undo", async ({ page }) => {
    await dataSupportPage.agents.interceptGetAgentRequest({
      body: { ...mockAgent, status: "STOPPED", skills: [mockAssignedSkill] },
    });
    await agentDetailPage.goto(MOCK_AGENT_ID);
    await agentDetailPage.configureButton().click();
    await agentDetailPage.skillsTab().click();

    await agentDetailPage.removeSkillButton().click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByRole("dialog").getByRole("heading", { name: "Remove github?" })).toBeVisible();
    await agentDetailPage.confirmRemoveSkillButton().click();

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
    await agentDetailPage.confirmRemoveSkillButton().click();
    await agentDetailPage.undoSkillButton().click();

    await expect(agentDetailPage.removeSkillButton()).toBeVisible();
    await expect(agentDetailPage.saveSkillsButton()).toBeDisabled();
  });

  test("adding a skill with required providers shows credentials section", async ({ page }) => {
    // github skill requires "github" provider — click Add for it
    await agentDetailPage.addSkillButton().first().click();

    await expect(page.getByText("Required credentials")).toBeVisible();
    await expect(
      page.getByText("Required credentials").locator("..").getByText("GitHub", { exact: true }),
    ).toBeVisible();
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

  test("shows Integrations section", async ({ page }) => {
    await expect(page.getByText("Add an integration", { exact: true })).toBeVisible();
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
      page.locator('section[aria-label="Integrations"]').getByText("Secret is used by a skill"),
    ).toBeVisible();
    await expect(page.getByText("Will be removed")).toBeVisible();
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

test.describe("Agent Detail Page — Personality tab (approval mode, OpenClaw)", () => {
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
      body: { ...mockAgent, status: "STOPPED", agent_type: "openclaw" },
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
  });

  test("shows Managed by OpenClaw instead of a command approval value", async ({ page }) => {
    await expect(page.getByText("Managed by OpenClaw")).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Command approval" })).toHaveCount(0);
  });

  test("editing the profile does not offer a command approval control", async ({ page }) => {
    await agentDetailPage.editButton().click();

    await expect(page.getByRole("combobox", { name: "Command approval" })).toHaveCount(0);
  });
});
