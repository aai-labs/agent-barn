import { expect, test, type Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { AgentConfigurationPage } from "../pages/agent-configuration-page.po";
import {
  MOCK_AGENT_ID,
  mockAgent,
  mockAgentAllowedActions,
} from "../pages/data-support/agent-data-support.po";
import { AgentSizeDataSupport, mockSize } from "../pages/data-support/agent-size-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { ORG_A_ID } from "../pages/data-support/organization-data-support.po";
import { DashboardPage } from "../pages/dashboard-page.po";

const GIB = 1024 ** 3;
const STANDARD = mockSize();
const LARGE = mockSize({
  id: "11111111-1111-4111-8111-00000000000a",
  name: "Large",
  cpu_request_millicores: 500,
  cpu_limit_millicores: 2000,
  memory_request_bytes: 2 * GIB,
  memory_limit_bytes: 4 * GIB,
  storage_bytes: 10 * GIB,
  is_default: false,
  sort_order: 1,
});
const RETIRED = mockSize({
  id: "11111111-1111-4111-8111-00000000000b",
  name: "Retired",
  enabled: false,
  is_default: false,
  sort_order: 2,
});

async function signIn(page: Page) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest();
  await data.users.interceptGetOrganizationsRequest();
  return data;
}

function platformOrganization(overrides: Record<string, unknown> = {}) {
  return {
    id: ORG_A_ID,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    name: "AAI Labs",
    description: "Starter organization",
    owner_email: "owner@example.com",
    owner_name: "Grace Hopper",
    llm_budget_usd: 100,
    llm_budget_duration: "30d",
    llm_own_budget_usd: null,
    is_trial: false,
    agent_size_ids: [],
    ...overrides,
  };
}

test.describe("Organizations choosing Agent sizes", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("a Platform Administrator lets an organization choose a size, then withdraws it", async ({ page }) => {
    const data = await signIn(page);
    const sizes = new AgentSizeDataSupport(page);
    await sizes.intercept({ sizes: [STANDARD, { ...LARGE, agent_count: 2 }, RETIRED] });
    const organization = platformOrganization();
    await data.organizations.interceptGetPlatformOrganization({ organization });
    const { writes } = await sizes.interceptSetOrganizationSizes(organization);

    await page.goto(`/dashboard/platform/organizations/${ORG_A_ID}`);
    const card = page.getByRole("region", { name: "Agent sizes" });
    const toggle = card.getByRole("switch", { name: "Can choose CPU & memory" });
    await expect(card).toContainText("Every agent runs on Standard, the default");
    await expect(toggle).toHaveAttribute("aria-checked", "false");

    await toggle.click();
    // A disabled size is not offered to an organization that does not have it already.
    await expect(card.getByRole("checkbox", { name: "Retired" })).toHaveCount(0);
    await expect(card.getByRole("button", { name: "Save" })).toBeDisabled();
    await expect(card).toContainText("Choose at least one size, or turn choosing off.");
    await card.getByRole("checkbox", { name: "Large" }).click();
    await card.getByRole("button", { name: "Save" }).click();

    await expect(card.getByRole("button", { name: "Save" })).toHaveCount(0);
    await expect(card.getByRole("checkbox", { name: "Large" })).toBeChecked();
    expect(writes).toEqual([{ agent_size_ids: [LARGE.id] }]);

    await toggle.click();
    await expect(card.getByRole("checkbox", { name: "Large" })).toHaveCount(0);
    await expect(card.getByTestId("agent-sizes-withdraw-note")).toContainText("2 agents on Large stay on it");
    await card.getByRole("button", { name: "Save" }).click();

    await expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(writes).toEqual([{ agent_size_ids: [LARGE.id] }, { agent_size_ids: [] }]);
  });

  test("a disabled size an organization still has stays listed until it is withdrawn", async ({ page }) => {
    const data = await signIn(page);
    const sizes = new AgentSizeDataSupport(page);
    await sizes.intercept({ sizes: [STANDARD, LARGE, RETIRED] });
    const organization = platformOrganization({ agent_size_ids: [LARGE.id, RETIRED.id] });
    await data.organizations.interceptGetPlatformOrganization({ organization });
    const { writes } = await sizes.interceptSetOrganizationSizes(organization);

    await page.goto(`/dashboard/platform/organizations/${ORG_A_ID}`);
    const card = page.getByRole("region", { name: "Agent sizes" });
    const retired = card.getByRole("checkbox", { name: "Retired" });
    await expect(retired).toBeChecked();
    await expect(card).toContainText("(disabled: agents on it keep it)");

    await retired.click();
    await expect(retired).toBeDisabled();
    await card.getByRole("button", { name: "Save" }).click();

    await expect(card.getByRole("button", { name: "Save" })).toHaveCount(0);
    expect(writes).toEqual([{ agent_size_ids: [LARGE.id] }]);
  });

  test("an owner hires an agent on an allowed size, with the default preselected", async ({ page }) => {
    const data = await signIn(page);
    await data.agents.interceptGetAgentsRequest();
    await data.agents.interceptGetAgentHealthRequest();
    await data.agents.interceptGetTemplatesRequest();
    await data.agents.interceptGetModelsRequest();
    await data.agents.interceptNameSuggestionRequest();
    await data.agents.interceptCreateAgentRequest({ body: { ...mockAgent, status: "STOPPED" } });
    await data.agents.interceptStartAgentRequest();
    await new AgentSizeDataSupport(page).interceptOrganizationSizes({ allowed: [LARGE] });

    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await dashboard.openHireCard();
    await page.getByRole("combobox", { name: "Template", exact: true }).click();
    await page.getByRole("option", { name: "General Purpose · v1" }).click();

    const size = page.getByRole("combobox", { name: "CPU & memory" });
    await expect(size).toHaveText("Standard · 0.5 vCPU · 1 GiB · 1 GiB disk (default)");
    await size.click();
    await page.getByRole("option", { name: "Large · 2 vCPU · 4 GiB · 10 GiB disk" }).click();

    const create = page.waitForRequest((request) => request.url().endsWith("/agents") && request.method() === "POST");
    await page.getByRole("button", { name: "Hire Agent", exact: true }).click();
    expect((await create).postDataJSON()).toEqual(expect.objectContaining({ agent_size_id: LARGE.id }));
  });

  test("an organization that cannot choose is not asked when hiring", async ({ page }) => {
    const data = await signIn(page);
    await data.agents.interceptGetAgentsRequest();
    await data.agents.interceptGetAgentHealthRequest();
    await data.agents.interceptGetTemplatesRequest();
    await data.agents.interceptGetModelsRequest();
    await data.agents.interceptNameSuggestionRequest();
    await new AgentSizeDataSupport(page).interceptOrganizationSizes();

    const dashboard = new DashboardPage(page);
    await dashboard.goto();
    await dashboard.openHireCard();

    await expect(page.getByRole("heading", { name: "Build your own agent" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "CPU & memory" })).toHaveCount(0);
  });

  test("an owner changes a running agent's size and is told it applies on restart", async ({ page }) => {
    const data = await signIn(page);
    const agent = {
      ...mockAgent,
      agent_size_id: null,
      agent_size: STANDARD,
      pending_size: false,
      allowed_actions: [...mockAgentAllowedActions, "agent.size.manage"],
    };
    await data.agents.interceptGetAgentRequest({ body: agent });
    await data.agents.interceptGetAgentConfigurationRequest();
    await data.agents.interceptGetTemplatesRequest();
    await data.agents.interceptGetTemplateVersionsRequest();
    const sizes = new AgentSizeDataSupport(page);
    await sizes.interceptOrganizationSizes({ allowed: [LARGE] });
    const { writes } = await sizes.interceptSetAgentSize(agent, [STANDARD, LARGE]);

    const configuration = new AgentConfigurationPage(page);
    await configuration.goto(MOCK_AGENT_ID, TEST_ORG_ID);
    const tile = page.getByTestId("agent-size-tile");
    const size = tile.getByRole("combobox", { name: "CPU & memory" });
    await expect(size).toHaveText("Standard · 0.5 vCPU · 1 GiB · 1 GiB disk (default)");
    await expect(page.getByTestId("agent-pending-size-note")).toHaveCount(0);

    await size.click();
    await page.getByRole("option", { name: "Large · 2 vCPU · 4 GiB · 10 GiB disk" }).click();

    await expect(size).toHaveText("Large · 2 vCPU · 4 GiB · 10 GiB disk");
    await expect(page.getByTestId("agent-pending-size-note")).toHaveText("Pending: applies on restart");
    await expect(page.getByTestId("agent-pending-size-restart")).toBeEnabled();
    expect(writes).toEqual([{ agent_size_id: LARGE.id }]);
  });

  test("an owner sees a size the platform set as locked, with no picker", async ({ page }) => {
    const data = await signIn(page);
    await data.agents.interceptGetAgentRequest({
      body: {
        ...mockAgent,
        agent_size_id: LARGE.id,
        agent_size: LARGE,
        agent_size_set_by_platform: true,
        pending_size: false,
        allowed_actions: [...mockAgentAllowedActions, "agent.size.manage"],
      },
    });
    await data.agents.interceptGetAgentConfigurationRequest();
    await data.agents.interceptGetTemplatesRequest();
    await data.agents.interceptGetTemplateVersionsRequest();
    await new AgentSizeDataSupport(page).interceptOrganizationSizes({ allowed: [LARGE] });

    await new AgentConfigurationPage(page).goto(MOCK_AGENT_ID, TEST_ORG_ID);
    const tile = page.getByTestId("agent-size-tile");

    await expect(tile).toContainText("Large · 2 vCPU · 4 GiB · 10 GiB disk");
    await expect(tile.getByTestId("agent-size-set-by-platform")).toHaveText("Set by platform");
    await expect(tile.getByRole("combobox")).toHaveCount(0);
  });

  test("an agent editor sees the size but cannot change it", async ({ page }) => {
    const data = await signIn(page);
    await data.agents.interceptGetAgentRequest({
      body: { ...mockAgent, agent_size_id: null, agent_size: STANDARD, pending_size: false },
    });
    await data.agents.interceptGetAgentConfigurationRequest();
    await data.agents.interceptGetTemplatesRequest();
    await data.agents.interceptGetTemplateVersionsRequest();
    await new AgentSizeDataSupport(page).interceptOrganizationSizes({ allowed: [LARGE] });

    await new AgentConfigurationPage(page).goto(MOCK_AGENT_ID, TEST_ORG_ID);
    const tile = page.getByTestId("agent-size-tile");

    await expect(tile).toContainText("Standard · 0.5 vCPU · 1 GiB · 1 GiB disk(default)");
    await expect(tile.getByRole("combobox")).toHaveCount(0);
  });
});
