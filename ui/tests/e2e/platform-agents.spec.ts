import { expect, test } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { AppNavigation } from "../pages/app-navigation.po";
import { AgentSizeDataSupport, mockSize } from "../pages/data-support/agent-size-data-support.po";
import { DataSupport } from "../pages/data-support/data-support.po";
import { mockPlatformAgent, PlatformAgentDataSupport } from "../pages/data-support/platform-agent-data-support.po";
import { PlatformAgentsPage } from "../pages/platform-agents-page.po";

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

const ACME_ID = "44444444-4444-4444-8444-00000000000a";
const SALLY = mockPlatformAgent();
const REPORTER = mockPlatformAgent({
  id: "33333333-3333-4333-8333-000000000002",
  name: "Reporter",
  status: "STOPPED",
  agent_type: "HERMES",
});
const OVERRIDDEN = mockPlatformAgent({
  id: "33333333-3333-4333-8333-000000000003",
  name: "Cruncher",
  organization_id: ACME_ID,
  organization_name: "Acme",
  agent_size_id: LARGE.id,
  agent_size: LARGE,
  agent_size_set_by_platform: true,
  pending_size: true,
});

test.describe("Platform Agents (platform_admin)", () => {
  let agentsPage: PlatformAgentsPage;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    agentsPage = new PlatformAgentsPage(page);
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({ userContext: { ...UserContext, is_platform_admin: true } });
    await data.users.interceptGetOrganizationsRequest();
    await new AgentSizeDataSupport(page).intercept({ sizes: [STANDARD, LARGE, RETIRED] });
  });

  test("lists every agent grouped by organization, with the size each runs on", async ({ page }) => {
    await new PlatformAgentDataSupport(page).intercept({ agents: [OVERRIDDEN, REPORTER, SALLY] });

    await agentsPage.goto();

    await expect(agentsPage.heading()).toBeVisible();
    await expect(agentsPage.organization("Acme")).toContainText("1 agent");
    await expect(agentsPage.organization("AAI Labs")).toContainText("2 agents");
    await expect(agentsPage.row(SALLY.id)).toContainText("Standard · 0.5 vCPU · 1 GiB · 1 GiB disk(default)");
    await expect(agentsPage.row(REPORTER.id)).toContainText("Hermes");
    await expect(agentsPage.row(OVERRIDDEN.id)).toContainText("Large · 2 vCPU · 4 GiB · 10 GiB disk");
    await expect(agentsPage.row(OVERRIDDEN.id)).toContainText("Set by platform");
    await expect(agentsPage.row(OVERRIDDEN.id)).toContainText("Pending: applies on restart");
    await expect(new AppNavigation(page).mainLink("Agents")).toHaveAttribute("aria-current", "page");
  });

  test("gives one agent a size its organization can't choose, offering only enabled sizes", async ({ page }) => {
    const { writes } = await new PlatformAgentDataSupport(page).intercept({
      agents: [SALLY],
      sizes: [STANDARD, LARGE, RETIRED],
    });
    await agentsPage.goto();

    await agentsPage.openOverride("Sally");
    await agentsPage.dialog().getByRole("combobox", { name: "Spec" }).click();
    await expect(page.getByRole("option", { name: /Retired/ })).toHaveCount(0);
    await page.getByRole("option", { name: "Large · 2 vCPU · 4 GiB · 10 GiB disk" }).click();
    await agentsPage.setSize();

    await expect(agentsPage.dialog()).toBeHidden();
    expect(writes).toEqual([{ agentId: SALLY.id, body: { agent_size_id: LARGE.id } }]);
    await expect(agentsPage.row(SALLY.id)).toContainText("Large · 2 vCPU · 4 GiB · 10 GiB disk");
    await expect(agentsPage.row(SALLY.id)).toContainText("Set by platform");
    await expect(agentsPage.row(SALLY.id)).toContainText("Pending: applies on restart");
  });

  test("clears an override, putting the agent back on the default", async ({ page }) => {
    const { writes } = await new PlatformAgentDataSupport(page).intercept({
      agents: [OVERRIDDEN],
      sizes: [STANDARD, LARGE],
    });
    await agentsPage.goto();

    await agentsPage.openOverride("Cruncher");
    await agentsPage.clearOverride();

    await expect(agentsPage.dialog()).toBeHidden();
    expect(writes).toEqual([{ agentId: OVERRIDDEN.id, body: { agent_size_id: null } }]);
    await expect(agentsPage.row(OVERRIDDEN.id)).toContainText("Standard · 0.5 vCPU · 1 GiB · 1 GiB disk(default)");
    await expect(agentsPage.row(OVERRIDDEN.id)).not.toContainText("Set by platform");
  });

  test("restarts an agent whose size is pending, after confirming", async ({ page }) => {
    const { restarts } = await new PlatformAgentDataSupport(page).intercept({ agents: [OVERRIDDEN] });
    await agentsPage.goto();
    const restart = agentsPage.row(OVERRIDDEN.id).getByRole("button", { name: "Restart Cruncher" });

    await restart.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("It stops and starts again on Large");
    await dialog.getByRole("button", { name: "Restart", exact: true }).click();

    await expect(dialog).toBeHidden();
    expect(restarts).toEqual([OVERRIDDEN.id]);
    await expect(agentsPage.row(OVERRIDDEN.id)).not.toContainText("Pending: applies on restart");
  });

  test("starts an agent that is not running", async ({ page }) => {
    const { restarts } = await new PlatformAgentDataSupport(page).intercept({ agents: [REPORTER] });
    await agentsPage.goto();

    await agentsPage.row(REPORTER.id).getByRole("button", { name: "Start Reporter" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Start", exact: true }).click();

    await expect(page.getByRole("dialog")).toBeHidden();
    expect(restarts).toEqual([REPORTER.id]);
    await expect(agentsPage.row(REPORTER.id)).toContainText("running");
  });

  test("searches by agent or organization name", async ({ page }) => {
    const { listQueries } = await new PlatformAgentDataSupport(page).intercept({
      agents: [OVERRIDDEN, REPORTER, SALLY],
    });
    await agentsPage.goto();
    await expect(agentsPage.row(SALLY.id)).toBeVisible();

    await agentsPage.search("acme");

    await expect(agentsPage.row(SALLY.id)).toHaveCount(0);
    await expect(agentsPage.row(OVERRIDDEN.id)).toBeVisible();
    expect(listQueries.at(-1)?.get("search")).toBe("acme");
  });
});
