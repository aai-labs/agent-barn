import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { AgentConfigurationPage } from "../pages/agent-configuration-page.po";
import { MOCK_AGENT_ID, mockAgent } from "../pages/data-support/agent-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { agentSettings, organizationLlmBudget } from "../pages/data-support/organization-data-support.po";
import { SettingsSpendLimitsPage } from "../pages/settings-spend-limits.po";

const COSTS_URL = `/dashboard/${TEST_ORG_ID}/costs`;

test.describe("Spend limit status on Costs", () => {
  let data: DataSupport;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.costs.interceptOrgFilterOptions();
    await data.costs.interceptOrgSummary();
    await data.costs.interceptOrgList({ items: [], total: 0 });
  });

  test("shows spend against the limit and links to where limits are managed", async ({ page }) => {
    await data.organizations.interceptGetOrganizationLlmBudget({
      organizationId: TEST_ORG_ID,
      budget: organizationLlmBudget({ limit_usd: 40, own_limit_usd: 40, spend_usd: 12.5 }),
    });
    await page.goto(COSTS_URL);

    const status = page.getByRole("region", { name: "Model spend limit" });
    await expect(status).toContainText("$12.50 of $40.00 used this month");
    await expect(status.getByRole("link", { name: /manage limits/i })).toHaveAttribute(
      "href",
      `/dashboard/${TEST_ORG_ID}/settings?tab=spend-limits`,
    );
    // Status only: the limit is changed in Settings, not here.
    await expect(status.getByRole("textbox")).toHaveCount(0);
  });

  test("someone who may not change limits is not sent to change them", async ({ page }) => {
    await data.organizations.interceptGetOrganizationLlmBudget({
      organizationId: TEST_ORG_ID,
      budget: organizationLlmBudget({ can_manage: false }),
    });
    await page.goto(COSTS_URL);

    await expect(page.getByRole("region", { name: "Model spend limit" })).toBeVisible();
    await expect(page.getByRole("link", { name: /manage limits/i })).toHaveCount(0);
  });
});

test.describe("Settings · Spend limits", () => {
  let data: DataSupport;
  let limits: SettingsSpendLimitsPage;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    limits = new SettingsSpendLimitsPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.organizations.interceptGetOrganization();
    await data.organizations.interceptAgentSettings();
    await data.agents.interceptAgentLlmBudgets();
  });

  test("shows every level of the chain in one place", async () => {
    await data.organizations.interceptGetOrganizationLlmBudget({
      organizationId: TEST_ORG_ID,
      budget: organizationLlmBudget({ limit_usd: 40, own_limit_usd: 40, spend_usd: 12.5 }),
    });
    await limits.open();

    await expect(limits.organizationLimit).toContainText("$40.00 per month");
    await expect(limits.organizationLimit).toContainText("$100.00 per month");
    await expect(limits.defaultAgentLimit).toContainText("$25.00 per month");
    await expect(limits.defaultAgentLimit).toContainText("of your $40.00 organization limit");
    await expect(limits.agentLimits.getByRole("row", { name: /Support Bot/ })).toContainText("Default");
    await expect(limits.agentLimits.getByRole("row", { name: /Research Bot/ })).toContainText("Own limit");
    await expect(limits.agentLimits.getByRole("row", { name: /Research Bot/ })).toContainText("limit reached");
  });

  test("each Agent row leads to that Agent's limit", async () => {
    await data.organizations.interceptGetOrganizationLlmBudget({ organizationId: TEST_ORG_ID });
    await limits.open();

    await expect(limits.agentLimits.getByRole("link", { name: "Change Support Bot's limit" })).toHaveAttribute(
      "href",
      `/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/configuration?section=spend`,
    );
  });

  test("lowering the organization limit says what it pulls down before saving", async () => {
    await data.organizations.interceptGetOrganizationLlmBudget({ organizationId: TEST_ORG_ID });
    await data.organizations.interceptAgentSettings({ settings: agentSettings({ default_agent_llm_budget_usd: 30 }) });
    const requests = await data.organizations.interceptSetOrganizationOwnLlmBudget({
      organizationId: TEST_ORG_ID,
    });
    await limits.open();

    await limits.editOrganizationLimit();
    await limits.setLowerOrganizationLimit("20");
    await limits.apply("organization", "Save limit");

    await expect(limits.dialog).toContainText("limited to $20.00 per month, straight away");
    await expect(limits.dialog).toContainText("default Agent limit will be lowered from $30.00 to $20.00");
    // Research Bot's own $60 is above the new limit; Support Bot follows the default.
    await expect(limits.dialog).toContainText("Lowered to fit: Research Bot ($60.00 → $20.00)");
    // $12.50 spent is under $20, so nothing is cut off and the confirm stays ordinary.
    await expect(limits.dialog.getByRole("button", { name: "Save limit" })).toBeVisible();
    expect(requests).toEqual([]);

    await limits.confirm("Save limit");
    await expect.poll(() => requests).toEqual([{ budget_usd: 20 }]);
  });

  test("a limit below what has already been spent says it stops every Agent", async () => {
    await data.organizations.interceptGetOrganizationLlmBudget({
      organizationId: TEST_ORG_ID,
      budget: organizationLlmBudget({ spend_usd: 42.1 }),
    });
    await limits.open();

    await limits.editOrganizationLimit();
    await limits.setLowerOrganizationLimit("20");
    await limits.apply("organization", "Save limit");

    await expect(limits.dialog).toContainText(
      "already spent $42.10 this month, so no Agent can make model calls until Oct 1, 2026",
    );
    await expect(limits.dialog.getByRole("button", { name: "Lower limit and stop Agents" })).toBeVisible();
  });

  test("a limit of zero says what it means before saving", async ({ page }) => {
    await data.organizations.interceptGetOrganizationLlmBudget({ organizationId: TEST_ORG_ID });
    await limits.open();

    await limits.editOrganizationLimit();
    await limits.setLowerOrganizationLimit("0");

    await expect(page.getByText("At $0, your organization's Agents can't make any model calls.")).toBeVisible();
  });

  test("Agents closest to their limit are listed first", async () => {
    await data.organizations.interceptGetOrganizationLlmBudget({ organizationId: TEST_ORG_ID });
    await limits.open();

    const firstRow = limits.agentLimits.getByRole("row").nth(1);
    await expect(firstRow).toContainText("Research Bot");
    await expect(firstRow).toContainText("$60.00 per month");
  });

  test("more than the organization is allowed is refused before any request", async ({ page }) => {
    await data.organizations.interceptGetOrganizationLlmBudget({ organizationId: TEST_ORG_ID });
    const requests = await data.organizations.interceptSetOrganizationOwnLlmBudget({
      organizationId: TEST_ORG_ID,
    });
    await limits.open();

    await limits.editOrganizationLimit();
    await limits.setLowerOrganizationLimit("150");

    await expect(page.getByText("This can't be more than $100.00.")).toBeVisible();
    await expect(limits.organizationLimit.getByRole("button", { name: "Save limit" })).toBeDisabled();
    expect(requests).toEqual([]);
  });

  test("going back to the maximum clears the organization's own limit", async () => {
    await data.organizations.interceptGetOrganizationLlmBudget({
      organizationId: TEST_ORG_ID,
      budget: organizationLlmBudget({ limit_usd: 40, own_limit_usd: 40 }),
    });
    const requests = await data.organizations.interceptSetOrganizationOwnLlmBudget({
      organizationId: TEST_ORG_ID,
    });
    await limits.open();

    await limits.editOrganizationLimit();
    await limits.useMaximum();
    await limits.apply("organization", "Save limit");
    await limits.confirm("Save limit");

    await expect.poll(() => requests).toEqual([{ budget_usd: null }]);
  });

  test("changing the default names who it reaches, and that it applies straight away", async () => {
    await data.organizations.interceptGetOrganizationLlmBudget({ organizationId: TEST_ORG_ID });
    await limits.open();

    await limits.editDefaultAgentLimit();
    await limits.enterDefaultAgentLimit("10");
    await limits.apply("default", "Change default");

    await expect(limits.dialog).toContainText(
      "4 Agents follow the default and will be limited to $10.00 straight away",
    );
    await limits.confirm("Change default");

    await expect(limits.defaultAgentLimit).toContainText("$10.00 per month");
    await expect(limits.defaultAgentLimit).toContainText("This organization");
  });
});

test.describe("An Agent's spend limit", () => {
  let data: DataSupport;
  let configuration: AgentConfigurationPage;
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);
    configuration = new AgentConfigurationPage(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.agents.interceptGetAgentRequest({ body: mockAgent });
    await data.agents.interceptGetAgentConfigurationRequest();
  });

  async function openSpendLimit() {
    await configuration.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    await configuration.sectionButton("Model spend limit").click();
  }

  test("a deep link opens the tab directly", async ({ page }) => {
    await data.agents.interceptAgentLlmBudget();
    await page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}/configuration?section=spend`);

    await expect(configuration.spendLimitSection()).toContainText("$25.00 per month");
  });

  test("an Agent without its own limit reads as following the default, with a way to it", async () => {
    await data.agents.interceptAgentLlmBudget();
    await openSpendLimit();

    const section = configuration.spendLimitSection();
    await expect(section).toContainText("$25.00 per month");
    await expect(section).toContainText("$7.50 of $25.00");
    await expect(section.getByRole("link", { name: /Default Agent limit, set in Settings/ })).toHaveAttribute(
      "href",
      `/dashboard/${TEST_ORG_ID}/settings?tab=spend-limits`,
    );
  });

  test("an owner gives the Agent a limit of its own", async ({ page }) => {
    const requests = await data.agents.interceptAgentLlmBudget();
    await openSpendLimit();

    await configuration.editSpendLimitButton().click();
    // An empty field follows the default, and says so.
    await expect(page.getByText(/Leave empty to use the default Agent limit \(\$25\.00 per month\)/)).toBeVisible();
    await expect(page.getByText("Enter an amount of zero or more.")).toHaveCount(0);
    await configuration.agentSpendLimitInput().fill("10");
    await configuration.saveSpendLimitButton().click();
    await expect(page.getByRole("dialog")).toContainText("limited to $10.00 per month straight away");
    await configuration.confirmSpendLimitButton().click();

    await expect.poll(() => requests).toEqual([{ budget_usd: 10 }]);
    await expect(configuration.spendLimitSection()).toContainText("This Agent's own limit");
  });

  test("a limit above the organization's is refused before any request", async ({ page }) => {
    const requests = await data.agents.interceptAgentLlmBudget();
    await openSpendLimit();

    await configuration.editSpendLimitButton().click();
    await configuration.agentSpendLimitInput().fill("150");

    await expect(page.getByText("This can't be more than $100.00.")).toBeVisible();
    await expect(configuration.agentSpendLimitInput()).toHaveAttribute("aria-invalid", "true");
    await expect(configuration.saveSpendLimitButton()).toBeDisabled();
    expect(requests).toEqual([]);
  });

  test("going back to the default clears the Agent's own limit", async () => {
    const requests = await data.agents.interceptAgentLlmBudget({
      budget: { own_limit_usd: 10, limit_usd: 10, source: "agent" },
    });
    await openSpendLimit();

    await configuration.editSpendLimitButton().click();
    await configuration.useDefaultSpendLimitButton().click();
    await configuration.saveSpendLimitButton().click();
    await configuration.confirmSpendLimitButton().click();

    await expect.poll(() => requests).toEqual([{ budget_usd: null }]);
  });

  test("a limit below what it has already spent says it stops the Agent", async ({ page }) => {
    await data.agents.interceptAgentLlmBudget({ budget: { spend_usd: 18 } });
    await openSpendLimit();

    await configuration.editSpendLimitButton().click();
    await configuration.agentSpendLimitInput().fill("10");
    await configuration.saveSpendLimitButton().click();

    await expect(page.getByRole("dialog")).toContainText("already spent $18.00 this month, so it will stop making model calls");
    await expect(page.getByRole("dialog").getByRole("button", { name: "Lower limit and stop Agent" })).toBeVisible();
  });

  test("an Agent at its limit says so, with a way to raise it", async () => {
    await data.agents.interceptAgentLlmBudget({ budget: { state: "exhausted", spend_usd: 25.4 } });
    await openSpendLimit();

    const section = configuration.spendLimitSection();
    await expect(section).toContainText("This Agent has reached its limit and can't make model calls until Oct 1, 2026.");
    await expect(section.getByRole("link", { name: "Raise the limit in Spend limits" })).toHaveAttribute(
      "href",
      `/dashboard/${TEST_ORG_ID}/settings?tab=spend-limits`,
    );
  });

  test("someone who may not change it sees it read-only", async () => {
    await data.agents.interceptAgentLlmBudget({ budget: { can_manage: false } });
    await openSpendLimit();

    await expect(configuration.spendLimitSection()).toContainText("$25.00 per month");
    await expect(configuration.editSpendLimitButton()).toHaveCount(0);
  });

  test("a viewer without access to the Agent's costs is not offered the tab", async () => {
    await data.agents.interceptGetAgentRequest({
      body: { ...mockAgent, allowed_actions: ["agent.read"] },
    });
    await configuration.goto(MOCK_AGENT_ID, TEST_ORG_ID);

    await expect(configuration.profileHeading()).toBeVisible();
    await expect(configuration.sectionButton("Model spend limit")).toHaveCount(0);
  });
});
