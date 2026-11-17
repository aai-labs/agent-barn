import { expect, test, type Page } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import { mockAgent } from "../pages/data-support/agent-data-support.po";
import { DashboardPage } from "../pages/dashboard-page.po";
import { ORG_A_ID, org, organizationLlmBudget } from "../pages/data-support/organization-data-support.po";

const FREE = { id: "00000000-0000-7000-8000-0000000071e0", key: "free", name: "Free", activation: "free" };
const CLOUD_1 = { id: "00000000-0000-7000-8000-0000000071e1", key: "cloud_1", name: "Cloud Tier 1", activation: "paid" };

function catalogTier(base: typeof FREE, enabled: boolean) {
  return {
    ...base,
    tagline: null,
    enabled,
    sort_order: 10,
    price_usd: base.activation === "paid" ? "20.00" : "0.00",
    price_note: null,
    monthly_usage_usd: "0.00",
    one_time_credit_usd: "10.00",
    agent_limit: 1,
    allowed_platform_keys: null,
    features: [],
    contact_url: null,
    is_system: base.key === "free",
    created_at: "2026-11-08T00:00:00Z",
    updated_at: "2026-11-08T00:00:00Z",
  };
}

function platformOrganization(overrides: Record<string, unknown> = {}) {
  return {
    id: ORG_A_ID,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    name: "AAI Labs",
    description: null,
    owner_email: "owner@example.com",
    owner_name: "Grace Hopper",
    llm_budget_usd: 100,
    llm_budget_duration: "30d",
    llm_own_budget_usd: null,
    is_trial: false,
    agent_limit: null,
    agent_limit_in_force: 10,
    tier_id: null,
    tier_assigned_by_platform: false,
    tier: null,
    over_tier: false,
    ...overrides,
  };
}

/** The organization read for one on a tier allowing these features. */
function organizationOnTier(features: string[], tier = FREE) {
  return org({ tier, entitlements: { features, allowed_platform_keys: ["agentbarn_telegram", "web"] }, over_tier: false });
}

async function signIn(page: Page) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest();
  await data.users.interceptGetOrganizationsRequest();
  return data;
}

test.describe("Platform · Organization tier", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  async function openOrganization(page: Page, organization: Record<string, unknown>, saved: unknown[] = []) {
    const data = await signIn(page);
    await data.organizations.interceptGetPlatformOrganizationMembers();
    await data.organizations.interceptGetOrganizationLlmCoverage();
    let current: Record<string, unknown> = platformOrganization(organization);
    await page.route("**/api/v1/platform/tiers", (route) =>
      route.fulfill({ json: [catalogTier(FREE, false), catalogTier(CLOUD_1, true)] }),
    );
    await page.route(`**/api/v1/platform/organizations/${ORG_A_ID}`, (route) => route.fulfill({ json: current }));
    await page.route(`**/api/v1/platform/organizations/${ORG_A_ID}/tier`, (route) => {
      const body = route.request().postDataJSON() as { tier_id: string | null };
      saved.push(body);
      const tier = [FREE, CLOUD_1].find((candidate) => candidate.id === body.tier_id) ?? null;
      current = { ...current, tier_id: body.tier_id, tier_assigned_by_platform: tier !== null, tier };
      return route.fulfill({ json: current });
    });
    await page.goto(`/dashboard/platform/organizations/${ORG_A_ID}`);
    return page.getByRole("region", { name: "Tier" });
  }

  test("a Platform Administrator puts an organization on a tier", async ({ page }) => {
    const saved: unknown[] = [];
    const card = await openOrganization(page, {}, saved);
    await expect(card).toContainText("No tier");

    await card.getByRole("button", { name: "Change" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("combobox", { name: "Tier" }).click();
    await expect(page.getByRole("option", { name: "Free (not offered)" })).toBeVisible();
    await page.getByRole("option", { name: "Cloud Tier 1" }).click();
    await dialog.getByRole("button", { name: "Save" }).click();

    await expect.poll(() => saved).toEqual([{ tier_id: CLOUD_1.id }]);
    await expect(card).toContainText("Cloud Tier 1");
  });

  test("an organization running more than its tier covers is flagged", async ({ page }) => {
    const card = await openOrganization(page, { tier_id: FREE.id, tier: FREE, over_tier: true, agent_limit_in_force: 1 });

    await expect(card).toContainText("Free");
    await expect(card.getByText("Over its tier")).toBeVisible();
    await expect(page.getByRole("region", { name: "Agents" })).toContainText("The Free tier's");
  });
});

test.describe("Organization · what its tier allows", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("without custom agents, the team page offers only the ready-made assistant", async ({ page }) => {
    const data = await signIn(page);
    await data.organizations.interceptGetOrganizationLlmBudget();
    await data.organizations.interceptGetOrganization({ organization: organizationOnTier(["team"]) });
    await data.agents.interceptGetAgentsRequest({ body: { page: 1, page_size: 50, total: 0, items: [] } });
    const dashboard = new DashboardPage(page);

    await dashboard.goto();

    await expect(page.getByRole("button", { name: "Try a ready-made assistant" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Hire a teammate" })).toHaveCount(0);
    await page.getByRole("button", { name: "Try a ready-made assistant" }).click();
    await expect(page.getByRole("heading", { name: "Your ready-made assistant" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Build your own agent", exact: true })).toHaveCount(0);
  });

  test("an agent its tier no longer covers shows it is on hold", async ({ page }) => {
    const data = await signIn(page);
    await data.organizations.interceptGetOrganizationLlmBudget();
    await data.organizations.interceptGetOrganization({ organization: organizationOnTier(["team"]) });
    const held = { ...mockAgent, status: "STOPPED", suspended_at: "2026-11-08T10:00:00Z", suspension_reason: "tier" };
    await data.agents.interceptGetAgentsRequest({ body: { page: 1, page_size: 50, total: 1, items: [held] } });
    const slack = { id: "bbbbbbbb-0000-4000-8000-000000000009", agent_id: mockAgent.id, agent_name: mockAgent.name, name: "Slack", platform_key: "slack", revision: 2, suspended_at: "2026-11-08T10:00:00Z" };
    await page.route(`**/api/v1/organizations/*/tier-holds`, (route) =>
      route.fulfill({ json: { agents: [], connections: [slack], webhooks: [], memory: [] } }),
    );
    const dashboard = new DashboardPage(page);

    await dashboard.goto();

    await expect(page.getByRole("heading", { name: mockAgent.name })).toBeVisible();
    await expect(page.getByText("On hold", { exact: true })).toBeVisible();
    const notice = page.getByRole("status").filter({ hasText: "On hold:" });
    await expect(notice).toContainText("Free doesn't cover everything your organization had. On hold: 1 agent and 1 channel.");
    await expect(notice.getByRole("link", { name: "Choose what to keep" })).toHaveAttribute(
      "href",
      /\/dashboard\/[^/]+\/settings\?tab=tier$/,
    );
  });

  test("with no tier yet, the team page points to choosing one instead of hiring", async ({ page }) => {
    const data = await signIn(page);
    // Created on credit from $0, so the budget reads as spent.
    const empty = { state: "exhausted", window: "once", limit_usd: 0, ceiling_usd: 0, spend_usd: 0, renews_at: null };
    await data.organizations.interceptGetOrganizationLlmBudget({ budget: organizationLlmBudget(empty) });
    const none = { id: "00000000-0000-7000-8000-0000000071ff", key: "none", name: "No tier", activation: "none" };
    await data.organizations.interceptGetOrganization({ organization: organizationOnTier([], none) });
    await data.agents.interceptGetAgentsRequest({ body: { page: 1, page_size: 50, total: 0, items: [] } });
    const dashboard = new DashboardPage(page);

    await dashboard.goto();

    await expect(page.getByText("Your organization has no tier yet. Subscribe to one to hire agents.")).toBeVisible();
    await expect(page.getByRole("link", { name: "Choose a tier" })).toHaveAttribute("href", /\/dashboard\/[^/]+\/billing$/);
    await expect(page.getByRole("button", { name: "Try a ready-made assistant" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Hire a teammate" })).toHaveCount(0);
    await expect(page.getByText(/used all its credit/)).toHaveCount(0);
  });

  test("without the team feature, members can't be invited", async ({ page }) => {
    const data = await signIn(page);
    await data.organizations.interceptListOrganizations();
    await data.organizations.interceptGetOrganization({
      organization: organizationOnTier([], { ...FREE, id: "00000000-0000-7000-8000-0000000071ff", key: "none", name: "No tier", activation: "none" }),
    });
    await data.organizations.interceptGetMembers();

    await page.goto(`/dashboard/${ORG_A_ID}/members`);

    await expect(page.getByText("ada@example.com")).toBeVisible();
    await expect(page.getByRole("button", { name: "Add member" })).toHaveCount(0);
    await expect(page.getByText("Your organization's tier, No tier, doesn't include inviting teammates.")).toBeVisible();
  });
});

test.describe("Organization · choosing what to keep", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  const KEPT = "aaaaaaaa-0000-4000-8000-000000000001";
  const HELD = "aaaaaaaa-0000-4000-8000-000000000002";
  const WEBHOOK = "bbbbbbbb-0000-4000-8000-000000000001";

  function holds(held: Set<string>, webhookHeld = true) {
    const heldAt = (id: string) => (held.has(id) ? "2026-11-08T10:00:00Z" : null);
    return {
      agents: [
        { id: KEPT, name: "Maya", status: "RUNNING", suspended_at: heldAt(KEPT) },
        { id: HELD, name: "Otto", status: "STOPPED", suspended_at: heldAt(HELD) },
      ],
      connections: [],
      webhooks: webhookHeld
        ? [{ id: WEBHOOK, agent_id: KEPT, agent_name: "Maya", name: "Jira", platform_key: null, revision: 3, suspended_at: "2026-11-08T10:00:00Z" }]
        : [],
      memory: [],
    };
  }

  test("an owner swaps which agent is kept and re-enables a webhook once the tier allows it", async ({ page }) => {
    const data = await signIn(page);
    await data.organizations.interceptGetOrganization({
      organization: org({
        agent_limit: 1,
        tier: CLOUD_1,
        entitlements: { features: ["agent_webhooks"], allowed_platform_keys: null },
        over_tier: false,
      }),
    });
    const held = new Set([HELD]);
    let current = holds(held);
    const posted: string[] = [];
    const patched: unknown[] = [];
    await page.route(`**/api/v1/organizations/${ORG_A_ID}/tier-holds`, (route) => route.fulfill({ json: current }));
    await page.route(`**/api/v1/organizations/${ORG_A_ID}/tier-holds/agents/*/*`, (route) => {
      const [agentId, action] = new URL(route.request().url()).pathname.split("/").slice(-2);
      posted.push(`${action} ${agentId}`);
      if (action === "hold") held.add(agentId);
      else held.delete(agentId);
      current = holds(held);
      return route.fulfill({ json: current });
    });
    await page.route(`**/api/v1/organizations/${ORG_A_ID}/agents/${KEPT}/webhooks/${WEBHOOK}`, (route) => {
      patched.push(route.request().postDataJSON());
      current = { ...current, webhooks: [] };
      return route.fulfill({ json: {} });
    });

    await page.goto(`/dashboard/${ORG_A_ID}/settings?tab=tier`);

    const agents = page.getByRole("region", { name: "Agents" });
    await expect(agents.getByRole("button", { name: "Release Otto" })).toBeDisabled();
    await agents.getByRole("button", { name: "Put Maya on hold" }).click();
    await agents.getByRole("button", { name: "Release Otto" }).click();
    await expect.poll(() => posted).toEqual([`hold ${KEPT}`, `release ${HELD}`]);

    await page.getByRole("region", { name: "Webhooks on hold" }).getByRole("button", { name: "Re-enable" }).click();
    await expect.poll(() => patched).toEqual([{ enabled: true, revision: 3 }]);
  });

  test("while the tier covers everything, there's nothing to choose", async ({ page }) => {
    const data = await signIn(page);
    await data.organizations.interceptGetOrganization({
      organization: org({ agent_limit: 4, tier: CLOUD_1, entitlements: { features: ["agent_webhooks"], allowed_platform_keys: null }, over_tier: false }),
    });
    await page.route(`**/api/v1/organizations/${ORG_A_ID}/tier-holds`, (route) => route.fulfill({ json: holds(new Set(), false) }));

    await page.goto(`/dashboard/${ORG_A_ID}/settings?tab=tier`);

    await expect(page.getByText("Everything your organization has is covered.")).toBeVisible();
    await expect(page.getByRole("region", { name: "Agents" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /on hold$/ })).toHaveCount(0);
  });
});
