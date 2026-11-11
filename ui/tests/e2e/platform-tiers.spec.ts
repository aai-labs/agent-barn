import { expect, test, type Page } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { DataSupport } from "../pages/data-support/data-support.po";

type TierJson = Record<string, unknown> & { id: string; key: string; name: string };

const EVERY_FEATURE = [
  "custom_agents",
  "integrations",
  "templates_and_skills",
  "workflows",
  "agent_webhooks",
  "agent_memory",
  "team",
  "priority_support",
];

function tier(overrides: Partial<TierJson> & Pick<TierJson, "id" | "key" | "name">): TierJson {
  return {
    tagline: null,
    activation: "paid",
    enabled: false,
    sort_order: 0,
    price_usd: "0.00",
    price_note: null,
    monthly_usage_usd: "0.00",
    one_time_credit_usd: "0.00",
    agent_limit: 1,
    allowed_platform_keys: null,
    features: [],
    contact_url: null,
    is_system: false,
    created_at: "2026-11-08T00:00:00Z",
    updated_at: "2026-11-08T00:00:00Z",
    ...overrides,
  };
}

const SEEDED: TierJson[] = [
  tier({
    id: "00000000-0000-7000-8000-0000000071e0",
    key: "free",
    name: "Free",
    activation: "free",
    sort_order: 10,
    one_time_credit_usd: "10.00",
    allowed_platform_keys: ["agentbarn_telegram", "web"],
    features: ["team"],
    is_system: true,
  }),
  tier({
    id: "00000000-0000-7000-8000-0000000071e1",
    key: "cloud_1",
    name: "Cloud Tier 1",
    sort_order: 20,
    price_usd: "20.00",
    price_note: "per month",
    monthly_usage_usd: "20.00",
    one_time_credit_usd: "10.00",
    features: EVERY_FEATURE.filter((feature) => feature !== "priority_support"),
  }),
  tier({
    id: "00000000-0000-7000-8000-0000000071e3",
    key: "pilot",
    name: "Supervised Pilot",
    activation: "contact",
    sort_order: 40,
    price_usd: "500.00",
    price_note: "per one-week pilot",
    agent_limit: 4,
    features: EVERY_FEATURE,
    contact_url: "https://agentbarn.dev/pricing",
  }),
  tier({
    id: "00000000-0000-7000-8000-0000000071ff",
    key: "none",
    name: "No tier",
    activation: "none",
    sort_order: 1000,
    agent_limit: 0,
    allowed_platform_keys: [],
    is_system: true,
  }),
];

/** Serves the catalog from memory, applying writes, and records each write. */
async function interceptTiers(page: Page) {
  let tiers = SEEDED.map((item) => ({ ...item }));
  const writes: { method: string; url: string; body?: unknown }[] = [];
  await page.route("**/api/v1/platform/tiers", async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as Partial<TierJson>;
      writes.push({ method: "POST", url: route.request().url(), body });
      const created = tier({ id: "33333333-3333-4333-8333-000000000001", key: "", name: "", ...body });
      tiers = [...tiers, created];
      return route.fulfill({ status: 201, json: created });
    }
    return route.fulfill({ json: tiers });
  });
  await page.route("**/api/v1/platform/tiers/*", async (route) => {
    const id = route.request().url().split("/").pop();
    const method = route.request().method();
    if (method === "DELETE") {
      writes.push({ method, url: route.request().url() });
      tiers = tiers.filter((item) => item.id !== id);
      return route.fulfill({ status: 204 });
    }
    const body = route.request().postDataJSON() as Partial<TierJson>;
    writes.push({ method, url: route.request().url(), body });
    tiers = tiers.map((item) => (item.id === id ? { ...item, ...body } : item));
    return route.fulfill({ json: tiers.find((item) => item.id === id) });
  });
  return { writes };
}

test.describe("Platform tiers (platform_admin)", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest({ userContext: { ...UserContext, is_platform_admin: true } });
    await data.users.interceptGetOrganizationsRequest();
  });

  test("lists the catalog with what each tier costs, grants and allows", async ({ page }) => {
    await interceptTiers(page);

    await page.goto("/dashboard/platform/settings?section=tiers");

    await expect(page.getByRole("heading", { name: "Tiers", level: 1 })).toBeVisible();
    const free = page.getByTestId("tier-row-free");
    await expect(free).toContainText("Free at sign-up");
    await expect(free).toContainText("$10.00 once");
    await expect(free).toContainText("Telegram (Agent Barn bot), Web Chat · Team");
    const cloud = page.getByTestId("tier-row-cloud_1");
    await expect(cloud).toContainText("$20.00 per month");
    await expect(cloud).toContainText("$20.00 monthly + $10.00 once");
    await expect(cloud).toContainText("Every platform");
    await expect(page.getByTestId("tier-row-pilot")).toContainText("$500.00 per one-week pilot");
    await expect(page.getByTestId("tier-row-pilot")).toContainText("Contact only");
    // The none tier never changes: no switch to turn on and no actions.
    await expect(page.getByRole("switch", { name: "No tier offered" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "No tier actions" })).toHaveCount(0);
  });

  test("the system's Free tier can be edited but not deleted", async ({ page }) => {
    await interceptTiers(page);
    await page.goto("/dashboard/platform/settings?section=tiers");

    await page.getByRole("button", { name: "Free actions", exact: true }).click();

    await expect(page.getByRole("menuitem", { name: "Edit" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Delete" })).toHaveCount(0);
  });

  test("adds a paid tier, sending dollars as decimal strings and only the chosen platforms", async ({ page }) => {
    const { writes } = await interceptTiers(page);
    await page.goto("/dashboard/platform/settings?section=tiers");

    await page.getByRole("button", { name: "Add tier" }).click();
    const dialog = page.getByTestId("tier-dialog");
    await dialog.getByLabel("Key", { exact: true }).fill("cloud_3");
    await dialog.getByLabel("Name", { exact: true }).fill("Cloud Tier 3");
    await dialog.getByLabel("Price (USD)").fill("250");
    await dialog.getByLabel("Monthly usage (USD)").fill("250");
    await dialog.getByLabel("One-time credit (USD)").fill("10");
    await dialog.getByLabel("Agents", { exact: true }).fill("10");
    await dialog.getByLabel("Every platform").click();
    await dialog.getByLabel("Slack").click();
    await dialog.getByLabel("Web Chat").click();
    await dialog.getByRole("button", { name: "Add tier" }).click();

    await expect(dialog).toBeHidden();
    expect(writes).toHaveLength(1);
    expect(writes[0].body).toMatchObject({
      key: "cloud_3",
      activation: "paid",
      name: "Cloud Tier 3",
      price_usd: "250.00",
      price_note: "per month",
      monthly_usage_usd: "250.00",
      one_time_credit_usd: "10.00",
      agent_limit: 10,
      allowed_platform_keys: ["slack", "web"],
      contact_url: null,
    });
    await expect(page.getByTestId("tier-row-cloud_3")).toContainText("Slack, Web Chat");
  });

  test("refuses a paid tier without a price, or a contact-only tier without a secure link, before sending", async ({
    page,
  }) => {
    const { writes } = await interceptTiers(page);
    await page.goto("/dashboard/platform/settings?section=tiers");

    await page.getByRole("button", { name: "Add tier" }).click();
    const dialog = page.getByTestId("tier-dialog");
    await dialog.getByLabel("Key", { exact: true }).fill("starter");
    await dialog.getByLabel("Name", { exact: true }).fill("Starter");
    await dialog.getByLabel("Price (USD)").fill("0");
    await dialog.getByLabel("Monthly usage (USD)").fill("5");
    await dialog.getByRole("button", { name: "Add tier" }).click();

    await expect(dialog.getByText("A paid tier needs a price above zero.")).toBeVisible();

    await dialog.getByRole("combobox", { name: "How organizations get it" }).click();
    await page.getByRole("option", { name: "Contact only" }).click();
    await expect(dialog.getByLabel("Monthly usage (USD)")).toHaveCount(0);
    await dialog.getByLabel("Contact link").fill("http://example.com/talk");
    await dialog.getByRole("button", { name: "Add tier" }).click();

    await expect(dialog.getByText("Enter a link starting with https://.")).toBeVisible();
    expect(writes).toHaveLength(0);
  });

  test("turns a tier on, so new organizations are offered it", async ({ page }) => {
    const { writes } = await interceptTiers(page);
    await page.goto("/dashboard/platform/settings?section=tiers");

    await page.getByRole("switch", { name: "Cloud Tier 1 offered" }).click();

    await expect(page.getByRole("switch", { name: "Cloud Tier 1 offered" })).toHaveAttribute("aria-checked", "true");
    expect(writes).toEqual([
      expect.objectContaining({ method: "PATCH", body: { enabled: true } }),
    ]);
  });

  test("deletes a tier after confirming", async ({ page }) => {
    const { writes } = await interceptTiers(page);
    await page.goto("/dashboard/platform/settings?section=tiers");

    await page.getByRole("button", { name: "Supervised Pilot actions", exact: true }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Delete tier" }).click();

    await expect(page.getByTestId("tier-row-pilot")).toHaveCount(0);
    expect(writes).toEqual([expect.objectContaining({ method: "DELETE" })]);
  });
});
