import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";

test.describe("Change Password", () => {
  let data: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);

    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.agents.interceptGetAgentsRequest();
    await data.users.interceptChangePasswordRequest();
  });

  test("Change password opens from user menu dropdown", async ({ page }) => {
    await page.goto("/dashboard");
    await page.getByTitle("Super User").click();
    await page.getByRole("button", { name: /change password/i }).click();

    await expect(
      page.getByRole("heading", { name: /change password/i }),
    ).toBeVisible();
  });

  test("Submitting form with correct old password succeeds", async ({
    page,
  }) => {
    await page.goto("/dashboard");
    await page.getByTitle("Super User").click();
    await page.getByRole("button", { name: /change password/i }).click();

    await page.getByLabel(/old password/i).fill("OldPass123");
    await page.getByLabel(/^new password$/i).fill("NewStrong456");
    await page.getByLabel(/confirm/i).fill("NewStrong456");

    await page.getByRole("button", { name: /^change password$/i }).click();

    await expect(page.getByText(/password changed/i)).toBeVisible();
  });
});
