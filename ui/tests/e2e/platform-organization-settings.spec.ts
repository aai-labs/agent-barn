import { expect, test, type Page } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";

const SETTINGS = "**/api/v1/platform/settings/organizations";

async function platformAdmin(page: Page, initial: Record<string, unknown>) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest();
  await data.users.interceptGetOrganizationsRequest();
  await data.platformMemory.intercept();
  let current = initial;
  const saved: unknown[] = [];
  await page.route(SETTINGS, (route) => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      saved.push(body);
      current = { ...current, ...body, updated_at: "2026-10-14T10:00:00Z" };
    }
    return route.fulfill({ json: current });
  });
  return saved;
}

test.describe("Platform · Organization settings", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("a Platform Administrator sets how many agents an organization may run by default", async ({ page }) => {
    const saved = await platformAdmin(page, { default_agent_limit: 10, updated_at: null });
    await page.goto("/dashboard/platform/settings");
    await page.getByRole("complementary").getByRole("link", { name: "Organizations", exact: true }).click();
    const section = page.getByRole("region", { name: "Organization settings" });
    await expect(section).toContainText("10 agents");

    await section.getByRole("button", { name: "Edit" }).click();
    await page.getByLabel("Default agent limit").fill("3");
    await page.getByRole("button", { name: "Save", exact: true }).click();

    await expect(section.getByRole("status")).toContainText("Organization settings saved.");
    await expect(section).toContainText("3 agents");
    expect(saved).toEqual([{ default_agent_limit: 3 }]);
  });

  for (const typed of ["0", "2.5", "1001", ""]) {
    test(`"${typed}" isn't a default agent limit`, async ({ page }) => {
      await platformAdmin(page, { default_agent_limit: 10, updated_at: null });
      await page.goto("/dashboard/platform/settings");
      await page.getByRole("complementary").getByRole("link", { name: "Organizations", exact: true }).click();
      const section = page.getByRole("region", { name: "Organization settings" });
      await section.getByRole("button", { name: "Edit" }).click();

      await page.getByLabel("Default agent limit").fill(typed);

      await expect(section.getByText("Enter a whole number from 1 to 1,000.")).toBeVisible();
      await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    });
  }
});
