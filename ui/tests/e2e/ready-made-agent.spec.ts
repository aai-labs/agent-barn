import { expect, test } from "@playwright/test";

import { mockCommunicationConnection } from "../fixtures/communication-connections";
import userContext from "../fixtures/user-context.json";
import { TEST_ORG_ID } from "../constants";
import { MOCK_AGENT_ID, mockAgent } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { DashboardPage } from "../pages/dashboard-page.po";
import { OnboardingDataSupport, TRIAL_CONNECTION_ID, TRIAL_DEEP_LINK, TRIAL_FRESH_DEEP_LINK, TRIAL_ORG_ID, trialUserContext } from "../pages/data-support/onboarding-data-support.po";

test.describe("Hiring choices", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    const trialOrganization = { ...userContext.organization_users[0].organization, is_trial: true };
    await data.users.interceptGetUserContextRequest({ userContext: {
      ...userContext,
      organization_users: [{ ...userContext.organization_users[0], organization: trialOrganization }],
    } });
    await data.organizations.interceptGetOrganization({ organization: {
      ...trialOrganization, trial_agent_limit: 5, trial_agent_limit_reached: false,
    } });
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptGetOrganizationLlmBudget();
    await data.agents.interceptGetAgentsRequest();
    await data.agents.interceptGetAgentHealthRequest();
    await data.agents.interceptNameSuggestionRequest();
    await data.agents.interceptGetTemplatesRequest();
    await data.agents.interceptGetModelsRequest();
    await data.agents.interceptCreateAgentRequest();
    await data.agents.interceptGetAgentRequest({ body: { ...mockAgent, status: "STOPPED" } });
    await data.communicationConnections.interceptQuickStartConnections(MOCK_AGENT_ID, TRIAL_CONNECTION_ID);
    const links = new OnboardingDataSupport(page, { organizationId: TEST_ORG_ID, agentId: MOCK_AGENT_ID, connectionId: TRIAL_CONNECTION_ID });
    await links.interceptLinkedAccounts();
    await links.interceptLinkTokens();
    await data.agents.interceptStartAgentRequest({ body: { ...mockAgent, status: "RUNNING" } });
  });

  test("ready-made setup waits for explicit hiring confirmation", async ({ page }) => {
    const requests = new DataSupport(page).agents.trackHiringRequests();
    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await dashboard.openHireChoices();
    await dashboard.chooseReadyMadeHiring();
    await expect(page.getByRole("heading", { name: "Your ready-made assistant" })).toBeVisible();
    await expect(page.getByText("General Purpose", { exact: true })).toBeVisible();
    expect(requests.creations).toHaveLength(0);
    expect(requests.starts).toHaveLength(0);
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(requests.creations).toHaveLength(0);
  });

  test("an existing team can use the onboarding Telegram linking flow", async ({ page }) => {
    const data = new DataSupport(page);
    const links = new OnboardingDataSupport(page, { organizationId: TEST_ORG_ID, agentId: MOCK_AGENT_ID, connectionId: TRIAL_CONNECTION_ID });
    await links.interceptLinkTokens({ statuses: ["waiting", "linked"] });
    const requests = data.agents.trackHiringRequests();
    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await dashboard.openHireChoices();
    expect(requests.creations).toHaveLength(0);
    await dashboard.chooseReadyMadeHiring();
    await page.getByRole("button", { name: "Hire assistant", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Say hi to @AgentBarnTestBot" })).toBeVisible();
    await expect(page.getByLabel("Agent name")).toHaveCount(0);
    await expect(page.getByRole("img", { name: "QR code that opens the bot" })).toBeVisible();
    await expect(page.getByText("Linked as @jane_doe")).toBeVisible();
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Your agent is live in Telegram." })).toBeVisible();
    await expect(page.getByRole("button", { name: "Go to dashboard", exact: true })).toHaveClass(/\baf-btn-primary\b/);
    await expect(page.getByRole("link", { name: "Open Telegram", exact: true })).not.toHaveClass(/\baf-btn-primary\b/);
    await page.getByRole("button", { name: "Go to dashboard", exact: true }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page).toHaveURL(`/dashboard/${TEST_ORG_ID}`);
    expect(requests.creations).toEqual([{
      name: "Brandon the Assistant", agent_type: "hermes", template_key: "general-purpose", approval_mode: "auto",
    }]);
    expect(requests.starts).toHaveLength(1);
  });

  test("closing Telegram setup leaves a way to resume from the Agent detail page", async ({ page }, testInfo) => {
    const data = new DataSupport(page);
    const requests = data.agents.trackHiringRequests();
    await data.agents.interceptGetConversationChannelsRequest();
    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await dashboard.openHireChoices();
    await dashboard.chooseReadyMadeHiring();
    await page.getByRole("button", { name: "Hire assistant", exact: true }).click();
    await expect(page.getByRole("link", { name: "Open in Telegram", exact: true })).toBeVisible();
    await dashboard.closeHireDialog();
    await data.agents.interceptGetAgentRequest({ body: { ...mockAgent, status: "RUNNING" } });
    await page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}`);
    await expect(page.getByText("Finish connecting Telegram", { exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("telegram-reminder.png"), fullPage: true, animations: "disabled" });
    await page.getByRole("button", { name: "Connect Telegram", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Say hi to @AgentBarnTestBot" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Open in Telegram", exact: true })).toHaveAttribute("href", TRIAL_DEEP_LINK);
    await dashboard.closeHireDialog();
    await page.reload();
    await page.getByRole("button", { name: "Connect Telegram", exact: true }).click();
    await expect(page.getByRole("img", { name: "QR code that opens the bot" })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("resumed-telegram.png"), fullPage: true, animations: "disabled" });
    expect(requests.creations).toHaveLength(1);
    expect(requests.starts).toHaveLength(1);
  });

  for (const condition of ["linked", "read-only", "stopped"] as const) {
    test(`Telegram resume respects ${condition} state`, async ({ page }) => {
      const data = new DataSupport(page);
      const requests = data.agents.trackHiringRequests();
      await data.agents.interceptGetAgentRequest({ body: {
        ...mockAgent,
        status: condition === "stopped" ? "STOPPED" : "RUNNING",
        ...(condition === "read-only" ? { allowed_actions: ["agent.read"] } : {}),
      } });
      await data.agents.interceptGetConversationChannelsRequest();
      await page.route(`**/api/v1/organizations/*/agents/${MOCK_AGENT_ID}/connections`, (route) => route.fulfill({ json: [{
        ...mockCommunicationConnection, id: TRIAL_CONNECTION_ID, agent_id: MOCK_AGENT_ID,
        platform_key: "agentbarn_telegram", external_identity: "@AgentBarnTestBot",
      }] }));
      const links = new OnboardingDataSupport(page, { organizationId: TEST_ORG_ID, agentId: MOCK_AGENT_ID, connectionId: TRIAL_CONNECTION_ID });
      await links.interceptLinkedAccounts(condition === "linked" ? [{
        id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", telegram_username: "jane_doe",
        linked_by_membership_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", created_at: "2026-10-07T12:00:00Z",
      }] : []);
      await page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}`);
      await expect(page.getByRole("heading", { name: "Maya", exact: true })).toBeVisible();
      if (condition === "stopped") {
        await expect(page.getByRole("button", { name: "Connect Telegram", exact: true })).toBeDisabled();
        await expect(page.getByText("Start your agent, then link your Telegram account to chat with it there.")).toBeVisible();
      } else {
        await expect(page.getByRole("button", { name: "Connect Telegram", exact: true })).toHaveCount(0);
      }
      expect(requests.creations).toHaveLength(0);
      expect(requests.starts).toHaveLength(0);
    });
  }

  test("Telegram is optional and skipping opens Web Chat without completing onboarding again", async ({ page }) => {
    const data = new DataSupport(page);
    const completions = await data.onboarding.interceptCompleteOnboarding();
    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await dashboard.openHireChoices();
    await dashboard.chooseReadyMadeHiring();
    await page.getByRole("button", { name: "Hire assistant", exact: true }).click();
    await expect(page.getByRole("link", { name: "Open in Telegram", exact: true })).toHaveAttribute("href", TRIAL_DEEP_LINK);
    await page.getByRole("button", { name: "Skip, I'll chat on the web" }).click();
    await expect(page).toHaveURL(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}?tab=chat`);
    expect(completions).toHaveLength(0);
  });

  test("retrying startup reuses both the created Agent and its Telegram Connection", async ({ page }) => {
    const data = new DataSupport(page);
    await data.agents.interceptStartAgentRequest({ status: 500, detail: "Startup temporarily unavailable" });
    const connections = await data.communicationConnections.interceptQuickStartConnections(MOCK_AGENT_ID, TRIAL_CONNECTION_ID);
    const requests = data.agents.trackHiringRequests();
    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await dashboard.openHireChoices();
    await dashboard.chooseReadyMadeHiring();
    await page.getByRole("button", { name: "Hire assistant", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Startup temporarily unavailable" })).toBeVisible();
    await data.agents.interceptStartAgentRequest({ body: { ...mockAgent, status: "RUNNING" } });
    await page.getByRole("button", { name: "Try again", exact: true }).click();
    await expect(page.getByRole("link", { name: "Open in Telegram", exact: true })).toBeVisible();
    expect(requests.creations).toHaveLength(1);
    expect(requests.starts).toHaveLength(2);
    expect(connections).toHaveLength(1);
  });

  test("a lost start response recovers an already running Agent", async ({ page }) => {
    const data = new DataSupport(page);
    await data.agents.interceptStartAgentRequest({ networkError: true });
    const requests = data.agents.trackHiringRequests();
    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await dashboard.openHireChoices();
    await dashboard.chooseReadyMadeHiring();
    await page.getByRole("button", { name: "Hire assistant", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: /reach the server/ })).toBeVisible();
    await data.agents.interceptGetAgentRequest({ body: { ...mockAgent, status: "RUNNING" } });
    await data.agents.interceptStartAgentRequest({ status: 409, detail: "Agent is already running" });
    await page.getByRole("button", { name: "Try again", exact: true }).click();
    await expect(page.getByRole("link", { name: "Open in Telegram", exact: true })).toBeVisible();
    expect(requests.creations).toHaveLength(1);
    expect(requests.starts).toHaveLength(1);
  });

  test("a lost connection-create response is recovered without creating duplicates", async ({ page }) => {
    const data = new DataSupport(page);
    const connections = await data.communicationConnections.interceptQuickStartConnections(MOCK_AGENT_ID, TRIAL_CONNECTION_ID, { loseFirstResponse: true });
    const requests = data.agents.trackHiringRequests();
    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await dashboard.openHireChoices();
    await dashboard.chooseReadyMadeHiring();
    await page.getByRole("button", { name: "Hire assistant", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: /reach the server/ })).toBeVisible();
    await page.getByRole("button", { name: "Try again", exact: true }).click();
    await expect(page.getByRole("link", { name: "Open in Telegram", exact: true })).toBeVisible();
    expect(requests.creations).toHaveLength(1);
    expect(connections).toHaveLength(1);
  });

  test("the shared linking screen replaces an expired link", async ({ page }) => {
    const links = new OnboardingDataSupport(page, { organizationId: TEST_ORG_ID, agentId: MOCK_AGENT_ID, connectionId: TRIAL_CONNECTION_ID });
    await links.interceptLinkTokens({ urls: [TRIAL_DEEP_LINK, TRIAL_FRESH_DEEP_LINK], statuses: ["waiting", "expired"] });
    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await dashboard.openHireChoices();
    await dashboard.chooseReadyMadeHiring();
    await page.getByRole("button", { name: "Hire assistant", exact: true }).click();
    await page.getByRole("link", { name: "Open in Telegram", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: /link expired/ })).toBeVisible();
    await expect(page.getByRole("link", { name: "Open in Telegram again" })).toHaveAttribute("href", TRIAL_FRESH_DEEP_LINK);
  });

  test("cancelling the choice creates nothing", async ({ page }) => {
    const data = new DataSupport(page);
    const requests = data.agents.trackHiringRequests();
    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await dashboard.openHireChoices();
    await dashboard.closeHireDialog();
    expect(requests.creations).toHaveLength(0);
    expect(requests.starts).toHaveLength(0);
  });

  test("a full trial shows neither hiring option as selected", async ({ page }) => {
    const data = new DataSupport(page);
    await data.users.interceptGetUserContextRequest({ userContext: trialUserContext });
    await data.organizations.interceptGetOrganization({ organization: {
      ...trialUserContext.organization_users[0].organization,
      trial_agent_limit: 1, trial_agent_limit_reached: true,
    } });
    await page.goto(`/dashboard/${TRIAL_ORG_ID}`);
    await new DashboardPage(page).openHireChoices();
    await expect(page.getByRole("button", { name: "View your agents", exact: true })).toBeVisible();
    for (const name of [/Ready-made assistant/, /Build your own/]) {
      await expect(page.getByRole("radio", { name })).not.toBeChecked();
      await expect(page.getByRole("radio", { name })).toBeDisabled();
    }
  });

  test("a failed capacity check blocks setup and can recover", async ({ page }) => {
    const data = new DataSupport(page);
    await data.users.interceptGetUserContextRequest({ userContext: trialUserContext });
    const trialLinks = new OnboardingDataSupport(page, { organizationId: TRIAL_ORG_ID, agentId: MOCK_AGENT_ID, connectionId: TRIAL_CONNECTION_ID });
    await trialLinks.interceptLinkedAccounts();
    await trialLinks.interceptLinkTokens();
    await data.organizations.interceptGetOrganization({ status: 503 });
    await page.goto(`/dashboard/${TRIAL_ORG_ID}`);
    const dashboard = new DashboardPage(page);
    await dashboard.openHireChoices();
    await expect(page.getByRole("alert").filter({ hasText: "We couldn't check your trial's agent limit." })).toBeVisible();
    await expect(page.getByRole("radio", { name: /Ready-made assistant/ })).toBeDisabled();
    await expect(page.getByRole("radio", { name: /Build your own/ })).toBeDisabled();
    await data.organizations.interceptGetOrganization({ organization: {
      ...trialUserContext.organization_users[0].organization,
      trial_agent_limit: 5,
      trial_agent_limit_reached: false,
    } });
    await page.getByRole("button", { name: "Try again", exact: true }).click();
    await expect(page.getByRole("radio", { name: /Ready-made assistant/ })).toBeEnabled();
    await dashboard.chooseReadyMadeHiring();
    await page.getByRole("button", { name: "Hire assistant", exact: true }).click();
    await expect(page.getByRole("link", { name: "Open in Telegram", exact: true })).toBeVisible();
  });

  for (const custom of [false, true]) {
    test(`an empty trial opens ${custom ? "custom" : "ready-made"} setup directly after checking capacity`, async ({ page }) => {
      const data = new DataSupport(page);
      await data.users.interceptGetUserContextRequest({ userContext: trialUserContext });
      await data.agents.interceptGetAgentsRequest({ body: { page: 1, page_size: 50, total: 0, items: [] } });
      await data.agents.interceptGetTemplatesRequest();
      await data.agents.interceptGetModelsRequest();
      await data.organizations.interceptGetOrganization({ organization: {
        ...trialUserContext.organization_users[0].organization,
        trial_agent_limit: 1,
        trial_agent_limit_reached: false,
      } });
      const links = new OnboardingDataSupport(page, { organizationId: TRIAL_ORG_ID, agentId: MOCK_AGENT_ID, connectionId: TRIAL_CONNECTION_ID });
      await links.interceptLinkedAccounts();
      await links.interceptLinkTokens();
      await page.goto(`/dashboard/${TRIAL_ORG_ID}`);
      if (custom) await new DashboardPage(page).openHireChoices();
      else await page.getByRole("button", { name: "Try a ready-made assistant" }).click();
      await expect(page.getByRole("heading", { name: custom ? "Build your own agent" : "Your ready-made assistant" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "How would you like to start?" })).toHaveCount(0);
    });
  }

  for (const width of [320, 768, 1024, 1440]) {
    test(`hiring choices fit ${width}px and support keyboard selection`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      const dashboard = new DashboardPage(page);
      await dashboard.goto();
      await dashboard.openHireChoices();
      const ready = page.getByRole("radio", { name: /Ready-made assistant/ });
      const custom = page.getByRole("radio", { name: /Build your own/ });
      await expect(ready).not.toBeChecked();
      await expect(custom).not.toBeChecked();
      await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeDisabled();
      await ready.focus();
      await ready.press("ArrowRight");
      await expect(custom).toBeChecked();
      await expect(custom).toBeFocused();
      await custom.press("ArrowLeft");
      await expect(ready).toBeChecked();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath("hiring-choices.png"), fullPage: true });
      await page.getByRole("button", { name: "Continue", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Your ready-made assistant" })).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath("ready-made-confirmation.png"), fullPage: true, animations: "disabled" });
      await page.getByRole("button", { name: "Hire assistant", exact: true }).click();
      await expect(page.getByRole("link", { name: "Open in Telegram", exact: true })).toBeVisible();
    });
  }
});
