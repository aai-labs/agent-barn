import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";

test.describe("Change Password", () => {
  let data: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);

    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.users.interceptChangePasswordRequest();
  });

  test("Account page shows change password form", async ({ page }) => {
    await page.goto("/dashboard/account");

    await expect(
      page.getByRole("heading", { name: /change password/i }),
    ).toBeVisible();
    await expect(page.getByLabel(/old password/i)).toBeVisible();
  });

  test("Submitting form with correct old password succeeds", async ({
    page,
  }) => {
    await page.goto("/dashboard/account");

    await page.getByLabel(/old password/i).fill("OldPass123");
    await page.getByLabel(/^new password$/i).fill("NewStrong456");
    await page.getByLabel(/confirm/i).fill("NewStrong456");

    await page.getByRole("button", { name: /^change password$/i }).click();

    await expect(page.getByText(/password changed/i)).toBeVisible();
  });

  test("Account link in user menu navigates to account page", async ({
    page,
  }) => {
    await data.agents.interceptGetAgentsRequest();
    await page.goto("/dashboard");
    await page.getByTitle("Grace Hopper").click();
    await page.getByRole("link", { name: /account/i }).click();

    await expect(page).toHaveURL(/\/dashboard\/account/);
  });
});
