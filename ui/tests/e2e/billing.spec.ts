import { expect, test, type Page } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { TEST_ORG_ID } from "../constants";
import { DataSupport } from "../pages/data-support/data-support.po";
import { organizationLlmBudget } from "../pages/data-support/organization-data-support.po";

const BILLING_URL = `/dashboard/${TEST_ORG_ID}/billing`;
const CHECKOUT_URL = "https://checkout.stripe.test/cs_test";

function billing(overrides: Record<string, unknown> = {}) {
  return {
    available: true,
    credit_usd: 10,
    spend_usd: 2.5,
    balance_usd: 7.5,
    min_purchase_usd: 5,
    max_purchase_usd: 500,
    credit_rate: 1,
    purchase_fee_percent: 0,
    history: [{ kind: "trial", credit_usd: 10, amount_paid_usd: null, created_at: "2026-10-01T09:00:00Z" }],
    ...overrides,
  };
}

async function signedIn(page: Page, { role = "OWNER", platformAdmin = false } = {}) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest({
    userContext: {
      ...UserContext,
      is_platform_admin: platformAdmin,
      organization_users: UserContext.organization_users.map((membership) => ({ ...membership, role })),
    },
  });
  await data.users.interceptGetOrganizationsRequest();
  await data.organizations.interceptGetOrganization();
  await data.agents.interceptGetAgentsRequest();
  await data.agents.interceptGetAgentHealthRequest();
  return data;
}

async function interceptBilling(page: Page, body: Record<string, unknown>) {
  const checkouts: unknown[] = [];
  await page.route(`**/api/v1/organizations/*/billing`, (route) => route.fulfill({ json: body }));
  await page.route(`**/api/v1/organizations/*/billing/checkout`, (route) => {
    checkouts.push(route.request().postDataJSON());
    return route.fulfill({ json: { url: CHECKOUT_URL } });
  });
  await page.route("https://checkout.stripe.test/**", (route) =>
    route.fulfill({ contentType: "text/html", body: "<html><body>Stripe Checkout</body></html>" }),
  );
  return checkouts;
}

test.describe("Billing", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("the owner sees their credit, balance and history", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing());
    await page.goto(BILLING_URL);

    await expect(page.getByRole("heading", { name: "Billing", exact: true })).toBeVisible();
    const balance = page.getByRole("region", { name: "Balance" });
    await expect(balance).toContainText("$7.50");
    await expect(balance).toContainText("$2.50 of $10.00 used");
    await expect(page.getByRole("table")).toContainText("Trial credit");
  });

  test("the owner buys credit and is sent to pay for it", async ({ page }) => {
    await signedIn(page);
    const checkouts = await interceptBilling(page, billing({ purchase_fee_percent: 5.5 }));
    await page.goto(BILLING_URL);

    await page.getByRole("button", { name: "Buy credit" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Credit to add").fill("20");
    await expect(dialog).toContainText("You'll pay $21.10");
    await dialog.getByRole("button", { name: "Continue to payment" }).click();

    await page.waitForURL(CHECKOUT_URL);
    expect(checkouts).toEqual([{ credit_usd: 20 }]);
  });

  test("an amount outside the platform's bounds is refused before any request", async ({ page }) => {
    await signedIn(page);
    const checkouts = await interceptBilling(page, billing());
    await page.goto(BILLING_URL);

    await page.getByRole("button", { name: "Buy credit" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Credit to add").fill("4");

    await expect(dialog.getByText("Choose between $5.00 and $500.00.")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Continue to payment" })).toBeDisabled();
    expect(checkouts).toEqual([]);
  });

  test("coming back from a payment says the credit is on its way", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing());
    await page.goto(`${BILLING_URL}?checkout=success`);

    await expect(page.getByRole("status").filter({ hasText: "Payment received" })).toBeVisible();
  });

  test("the owner gets a Billing tab only when credit can be bought", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing({ available: false }));
    await page.goto(`/dashboard/${TEST_ORG_ID}`);

    await expect(page.getByRole("link", { name: "Settings", exact: true }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Billing", exact: true })).toHaveCount(0);
  });

  test("the owner's Billing tab leads to the page", async ({ page }) => {
    await signedIn(page);
    await interceptBilling(page, billing());
    await page.goto(`/dashboard/${TEST_ORG_ID}`);

    await expect(page.getByRole("link", { name: "Billing", exact: true }).first()).toHaveAttribute("href", BILLING_URL);
  });

  test("an admin who isn't the owner gets no Billing tab", async ({ page }) => {
    await signedIn(page, { role: "ADMIN" });
    await interceptBilling(page, billing());
    await page.goto(`/dashboard/${TEST_ORG_ID}`);

    await expect(page.getByRole("link", { name: "Settings", exact: true }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Billing", exact: true })).toHaveCount(0);
  });

  test("an organization that has used all its credit is told, and its owner can buy more", async ({ page }) => {
    const data = await signedIn(page);
    await interceptBilling(page, billing({ spend_usd: 10.2, balance_usd: -0.2 }));
    await data.organizations.interceptGetOrganizationLlmBudget({
      organizationId: TEST_ORG_ID,
      budget: organizationLlmBudget({
        state: "exhausted",
        window: "once",
        limit_usd: 10,
        ceiling_usd: 10,
        spend_usd: 10.2,
        renews_at: null,
      }),
    });
    await page.goto(`/dashboard/${TEST_ORG_ID}`);

    const banner = page.getByRole("status").filter({ hasText: "used all its credit" });
    await expect(banner).toBeVisible();
    await expect(banner).not.toContainText("renew");
    await expect(banner.getByRole("link", { name: "Buy credit" })).toHaveAttribute("href", BILLING_URL);
  });
});

test.describe("Platform · Billing settings", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("a Platform Administrator sets the purchase bounds, rate and fee", async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.platformMemory.intercept();
    const saved: unknown[] = [];
    let current = {
      payments_enabled: true,
      min_purchase_usd: 5,
      max_purchase_usd: 500,
      credit_rate: 1,
      purchase_fee_percent: 0,
      updated_at: null,
    };
    await page.route("**/api/v1/platform/settings/billing", (route) => {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON() as Record<string, number>;
        saved.push(body);
        current = { ...current, ...body };
      }
      return route.fulfill({ json: current });
    });

    await page.goto("/dashboard/platform/settings");
    await page.getByRole("button", { name: "Billing" }).click();
    const section = page.getByRole("region", { name: "Billing" });
    await expect(section).toContainText("$5.00");

    await section.getByRole("button", { name: "Edit" }).click();
    await page.getByLabel("Smallest purchase").fill("10");
    await page.getByLabel("Purchase fee").fill("5.5");
    await page.getByRole("button", { name: "Save", exact: true }).click();

    await expect.poll(() => saved).toEqual([
      { min_purchase_usd: 10, max_purchase_usd: 500, credit_rate: 1, purchase_fee_percent: 5.5 },
    ]);
  });

  test("says when this deployment doesn't take payments", async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.platformMemory.intercept();
    await page.route("**/api/v1/platform/settings/billing", (route) =>
      route.fulfill({
        json: {
          payments_enabled: false,
          min_purchase_usd: 5,
          max_purchase_usd: 500,
          credit_rate: 1,
          purchase_fee_percent: 0,
          updated_at: null,
        },
      }),
    );

    await page.goto("/dashboard/platform/settings");
    await page.getByRole("button", { name: "Billing" }).click();

    await expect(page.getByText("This deployment doesn't take payments.")).toBeVisible();
  });
});
