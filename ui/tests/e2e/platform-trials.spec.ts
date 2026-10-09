import { expect, test, type Page } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";
import { ORG_A_ID } from "../pages/data-support/organization-data-support.po";

const TRIAL_SETTINGS = "**/api/v1/platform/settings/trial";

function trialOrganization(overrides: Record<string, unknown> = {}) {
  return {
    id: ORG_A_ID,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    name: "Jane's Organization",
    description: null,
    owner_email: "jane@example.com",
    owner_name: "Jane Doe",
    creator_email: "jane@example.com",
    creator_name: "Jane Doe",
    llm_budget_usd: 10,
    llm_budget_duration: "once",
    llm_own_budget_usd: null,
    is_trial: true,
    ...overrides,
  };
}

async function signInAsPlatformAdmin(page: Page) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest();
  await data.users.interceptGetOrganizationsRequest();
  return data;
}

test.describe("Platform trials", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("a Platform Administrator sets the trial credit", async ({ page }) => {
    const data = await signInAsPlatformAdmin(page);
    await data.platformMemory.intercept();
    const saved: unknown[] = [];
    await page.route(TRIAL_SETTINGS, async (route) => {
      if (route.request().method() === "PUT") {
        saved.push(route.request().postDataJSON());
        return route.fulfill({ json: { credit_usd: 25, agent_limit: 3, updated_at: "2026-10-07T12:00:00Z" } });
      }
      return route.fulfill({ json: { credit_usd: 10, agent_limit: 1, updated_at: null } });
    });

    await page.goto("/dashboard/platform/settings");
    await page.getByRole("button", { name: "Trials" }).click();

    await expect(page.getByTestId("saved-trial-credit")).toHaveText("$10.00");
    await expect(page.getByTestId("saved-trial-agent-limit")).toHaveText("1 agent");
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await page.getByLabel("Trial credit (USD)").fill("25");
    await page.getByLabel("Agents per trial").fill("3");
    await page.getByRole("button", { name: "Save", exact: true }).click();

    await expect(page.getByRole("status")).toContainText("Trial settings saved.");
    await expect(page.getByTestId("saved-trial-credit")).toHaveText("$25.00");
    await expect(page.getByTestId("saved-trial-agent-limit")).toHaveText("3 agents");
    expect(saved).toEqual([{ credit_usd: 25, agent_limit: 3, max_active_trials: null }]);
  });

  test("a Platform Administrator caps the active trials", async ({ page }) => {
    const data = await signInAsPlatformAdmin(page);
    await data.platformMemory.intercept();
    const saved: unknown[] = [];
    await page.route(TRIAL_SETTINGS, async (route) => {
      if (route.request().method() === "PUT") {
        saved.push(route.request().postDataJSON());
        return route.fulfill({
          json: { credit_usd: 10, agent_limit: 1, max_active_trials: 20, active_trials: 3, updated_at: null },
        });
      }
      return route.fulfill({
        json: { credit_usd: 10, agent_limit: 1, max_active_trials: null, active_trials: 3, updated_at: null },
      });
    });

    await page.goto("/dashboard/platform/settings");
    await page.getByRole("button", { name: "Trials" }).click();

    await expect(page.getByTestId("saved-trial-cap")).toHaveText("3 active, no cap");
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await page.getByLabel("Active trials at once").fill("20");
    await page.getByRole("button", { name: "Save", exact: true }).click();

    await expect(page.getByTestId("saved-trial-cap")).toHaveText("3 of 20 active");
    expect(saved).toEqual([{ credit_usd: 10, agent_limit: 1, max_active_trials: 20 }]);
  });

  test("a Platform Administrator removes the cap on active trials", async ({ page }) => {
    const data = await signInAsPlatformAdmin(page);
    await data.platformMemory.intercept();
    const saved: unknown[] = [];
    await page.route(TRIAL_SETTINGS, async (route) => {
      if (route.request().method() === "PUT") {
        saved.push(route.request().postDataJSON());
        return route.fulfill({
          json: { credit_usd: 10, agent_limit: 1, max_active_trials: null, active_trials: 3, updated_at: null },
        });
      }
      return route.fulfill({
        json: { credit_usd: 10, agent_limit: 1, max_active_trials: 20, active_trials: 3, updated_at: null },
      });
    });

    await page.goto("/dashboard/platform/settings");
    await page.getByRole("button", { name: "Trials" }).click();
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await page.getByLabel("Active trials at once").fill("");
    await page.getByRole("button", { name: "Save", exact: true }).click();

    await expect(page.getByTestId("saved-trial-cap")).toHaveText("3 active, no cap");
    expect(saved).toEqual([{ credit_usd: 10, agent_limit: 1, max_active_trials: null }]);
  });

  test("an invalid cap on active trials cannot be saved", async ({ page }) => {
    const data = await signInAsPlatformAdmin(page);
    await data.platformMemory.intercept();
    await page.route(TRIAL_SETTINGS, (route) =>
      route.fulfill({ json: { credit_usd: 10, agent_limit: 1, max_active_trials: null, active_trials: 0 } }),
    );

    await page.goto("/dashboard/platform/settings");
    await page.getByRole("button", { name: "Trials" }).click();
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await page.getByLabel("Active trials at once").fill("0");

    await expect(page.getByText("Enter a whole number from 1 to 100,000, or leave it empty.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  });

  test("an out-of-range credit cannot be saved", async ({ page }) => {
    const data = await signInAsPlatformAdmin(page);
    await data.platformMemory.intercept();
    await page.route(TRIAL_SETTINGS, (route) =>
      route.fulfill({ json: { credit_usd: 10, agent_limit: 1, updated_at: null } }),
    );

    await page.goto("/dashboard/platform/settings");
    await page.getByRole("button", { name: "Trials" }).click();
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    await page.getByLabel("Trial credit (USD)").fill("-5");
    await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();

    await page.getByLabel("Trial credit (USD)").fill("10");
    await page.getByLabel("Agents per trial").fill("0");
    await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  });

  test("a trial's one-off spend limit reads as a total", async ({ page }) => {
    const data = await signInAsPlatformAdmin(page);
    await data.organizations.interceptGetPlatformOrganizationMembers();
    await data.organizations.interceptGetOrganizationLlmCoverage();
    await data.organizations.interceptGetPlatformOrganization({ organization: trialOrganization() });

    await page.goto(`/dashboard/platform/organizations/${ORG_A_ID}`);

    await expect(page.getByText(/most this organization can spend is \$10\.00 in total/i)).toBeVisible();
  });

  test("a Platform Administrator ends a trial", async ({ page }) => {
    const data = await signInAsPlatformAdmin(page);
    await data.organizations.interceptGetPlatformOrganizationMembers();
    await data.organizations.interceptGetOrganizationLlmCoverage();
    const ended: unknown[] = [];
    const after = { is_trial: false, llm_budget_usd: 75, llm_budget_duration: "7d" };
    await page.route(`**/api/v1/platform/organizations/${ORG_A_ID}`, (route) =>
      route.fulfill({ json: trialOrganization(ended.length === 0 ? {} : after) }),
    );
    await page.route(`**/api/v1/platform/organizations/${ORG_A_ID}/end-trial`, (route) => {
      ended.push(route.request().postDataJSON());
      return route.fulfill({ json: trialOrganization(after) });
    });

    await page.goto(`/dashboard/platform/organizations/${ORG_A_ID}`);
    await expect(page.getByRole("heading", { name: "Free trial" })).toBeVisible();
    await page.getByRole("button", { name: "End trial" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("New spend limit").fill("75");
    await dialog.getByRole("combobox", { name: "Renewal period" }).click();
    await page.getByRole("option", { name: "per week" }).click();
    await dialog.getByRole("button", { name: "End trial" }).click();

    await expect(page.getByRole("heading", { name: "Free trial" })).toHaveCount(0);
    expect(ended).toEqual([{ budget_usd: 75, budget_duration: "7d" }]);
  });

  test("the organizations list marks trials", async ({ page }) => {
    const data = await signInAsPlatformAdmin(page);
    await data.organizations.interceptListOrganizations({
      items: [
        trialOrganization(),
        trialOrganization({ id: "33333333-3333-4333-8333-333333333333", name: "Acme", is_trial: false }),
      ],
    });

    await page.goto("/dashboard/platform/organizations");

    const trial = page.getByRole("link", { name: /Jane's Organization/ });
    await expect(trial.getByText("Trial", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: /Acme/ }).getByText("Trial", { exact: true })).toHaveCount(0);
  });

  test("an organization that is not a trial shows no trial card", async ({ page }) => {
    const data = await signInAsPlatformAdmin(page);
    await data.organizations.interceptGetPlatformOrganizationMembers();
    await data.organizations.interceptGetOrganizationLlmCoverage();
    await data.organizations.interceptGetPlatformOrganization();

    await page.goto(`/dashboard/platform/organizations/${ORG_A_ID}`);

    await expect(page.getByRole("heading", { name: /model spend limit/i })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Free trial" })).toHaveCount(0);
  });
});
