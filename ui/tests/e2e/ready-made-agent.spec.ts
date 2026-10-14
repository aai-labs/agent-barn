import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { MOCK_AGENT_ID } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { DashboardPage } from "../pages/dashboard-page.po";
import { TRIAL_ORG_ID, trialUserContext } from "../pages/data-support/onboarding-data-support.po";

test.describe("Hiring choices", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptGetOrganizationLlmBudget();
    await data.agents.interceptGetAgentsRequest();
    await data.agents.interceptGetAgentHealthRequest();
    await data.agents.interceptNameSuggestionRequest();
    await data.agents.interceptCreateAgentRequest();
    await data.agents.interceptStartAgentRequest();
  });

  for (const telegram of [false, true]) {
    test(`an existing team can hire a ready-made assistant and open ${telegram ? "channel setup" : "Web Chat"}`, async ({ page }) => {
      const data = new DataSupport(page);
      const requests = data.agents.trackHiringRequests();
      const dashboard = new DashboardPage(page);
      await dashboard.goto();
      await dashboard.openHireChoices();
      await expect(page.getByRole("radio", { name: /Build your own/ })).toBeVisible();
      expect(requests.creations).toHaveLength(0);
      await dashboard.chooseReadyMadeHiring();
      await dashboard.agentNameInput().fill("My ready-made assistant");
      await page.getByRole("button", { name: "Create assistant", exact: true }).click();
      await expect(page.getByRole("heading", { name: /is ready$/ })).toBeVisible();
      expect(requests.creations).toEqual([{
        name: "My ready-made assistant", agent_type: "hermes", template_key: "general-purpose", approval_mode: "auto",
      }]);
      expect(requests.starts).toHaveLength(1);
      await page.getByRole("button", { name: telegram ? "Connect Telegram" : "Chat on the web", exact: true }).click();
      const base = `/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}`;
      await expect(page).toHaveURL(telegram ? `${base}/configuration?section=channels&connect=true` : `${base}?tab=chat`);
    });
  }

  test("retrying a ready-made startup never creates a second agent", async ({ page }) => {
    const data = new DataSupport(page);
    await data.agents.interceptStartAgentRequest({ status: 500, detail: "Startup temporarily unavailable" });
    const requests = data.agents.trackHiringRequests();
    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await dashboard.openHireChoices();
    await dashboard.chooseReadyMadeHiring();
    await dashboard.agentNameInput().fill("Retry me");
    await page.getByRole("button", { name: "Create assistant", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Startup temporarily unavailable" })).toBeVisible();
    await data.agents.interceptStartAgentRequest();
    await page.getByRole("button", { name: "Start again", exact: true }).click();
    await expect(page.getByRole("heading", { name: /is ready$/ })).toBeVisible();
    expect(requests.creations).toHaveLength(1);
    expect(requests.starts).toHaveLength(2);
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

  test("a failed capacity check blocks setup and can recover", async ({ page }) => {
    const data = new DataSupport(page);
    await data.users.interceptGetUserContextRequest({ userContext: trialUserContext });
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
    await expect(dashboard.agentNameInput()).toBeVisible();
  });

  for (const width of [320, 768, 1024, 1440]) {
    test(`hiring choices fit ${width}px and support keyboard selection`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      const dashboard = new DashboardPage(page);
      await dashboard.goto();
      await dashboard.openHireChoices();
      const ready = page.getByRole("radio", { name: /Ready-made assistant/ });
      const custom = page.getByRole("radio", { name: /Build your own/ });
      await ready.focus();
      await ready.press("ArrowRight");
      await expect(custom).toBeChecked();
      await expect(custom).toBeFocused();
      await custom.press("ArrowLeft");
      await expect(ready).toBeChecked();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath("hiring-choices.png"), fullPage: true });
      await page.getByRole("button", { name: "Continue", exact: true }).click();
      await expect(dashboard.agentNameInput()).toBeVisible();
    });
  }
});
