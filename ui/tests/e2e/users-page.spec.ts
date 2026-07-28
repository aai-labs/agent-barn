import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";

const USERS_URL = "/dashboard/users";

test.describe("Users Page — Create & Delete", () => {
  let data: DataSupport;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    data = new DataSupport(page);

    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.users.interceptGetUsersRequest();
    await data.users.interceptCreateUserRequest();
    await data.users.interceptDeleteUserRequest();
    await data.users.interceptResetUserPasswordRequest();
  });

  test("Create user button opens dialog", async ({ page }) => {
    await page.goto(USERS_URL);

    await page.getByRole("button", { name: /create user/i }).click();
    await expect(
      page.getByRole("heading", { name: /create user/i }),
    ).toBeVisible();
  });

  test("Creating a user shows success toast", async ({ page }) => {
    await page.goto(USERS_URL);

    await page.getByRole("button", { name: /create user/i }).click();
    await page.getByLabel(/email/i).fill("new@example.com");
    await page.getByLabel(/^password$/i).fill("StrongPass123");
    // Global create-user must target an org (populated from the all-orgs picker).
    await page.getByLabel(/organization/i).selectOption({ label: "AAI Labs" });

    await page.getByRole("button", { name: /^create$/i }).click();

    await expect(page.getByText(/user created/i)).toBeVisible();
  });

  test("Delete button is not shown on current user card", async ({ page }) => {
    await data.users.interceptGetUsersRequest({
      body: {
        page: 1,
        page_size: 20,
        total: 1,
        items: [
          {
            id: "019db657-3269-75a0-90f1-decb91b987d6",
            created_at: "2024-01-01T00:00:00Z",
            updated_at: "2024-01-01T00:00:00Z",
            full_name: "Super User",
            email: "admin@aai-labs.com",
            is_platform_admin: true,
            email_verified_at: null,
          },
        ],
      },
    });

    await page.goto(USERS_URL);

    await expect(page.getByText("admin@aai-labs.com")).toBeVisible();
    await expect(
      page.getByRole("button", { name: /delete/i }),
    ).not.toBeVisible();
  });

  test("Deleting a user shows confirmation then success toast", async ({
    page,
  }) => {
    await page.goto(USERS_URL);

    await page.getByRole("button", { name: /delete/i }).first().click();
    await expect(page.getByText(/are you sure/i)).toBeVisible();

    await page.getByRole("button", { name: /^delete$/i }).click();

    await expect(page.getByText(/user deleted/i)).toBeVisible();
  });

  test("Reset password button opens dialog", async ({ page }) => {
    await page.goto(USERS_URL);

    await page.getByRole("button", { name: /reset password/i }).first().click();
    await expect(
      page.getByRole("heading", { name: /reset password/i }),
    ).toBeVisible();
  });

  test("Resetting a user password shows success toast", async ({ page }) => {
    await page.goto(USERS_URL);

    await page.getByRole("button", { name: /reset password/i }).first().click();
    await page.getByLabel(/^new password$/i).fill("NewStrong456");

    await page.getByRole("button", { name: /^reset$/i }).click();

    await expect(page.getByText(/password reset/i)).toBeVisible();
  });
});
