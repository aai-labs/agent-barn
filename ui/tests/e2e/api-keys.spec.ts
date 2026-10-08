import { expect, test } from "@playwright/test";

import { DataSupport } from "../pages/data-support/data-support.po";

test.describe("Personal API keys", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.users.interceptChangePasswordRequest();

    let keys: Record<string, unknown>[] = [];
    await page.route("**/api/v1/auth/me/api-keys", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({ json: keys });
        return;
      }
      const input = route.request().postDataJSON() as { name: string; access_mode: string };
      const key = {
        id: "6e6df475-7eaf-474f-a4ef-c3eddb047fae",
        name: input.name,
        token_prefix: "abk_example1",
        access_mode: input.access_mode,
        created_at: "2026-09-30T10:00:00Z",
        expires_at: null,
        revoked_at: null,
        last_used_at: null,
        status: "ACTIVE",
      };
      keys = [key];
      await route.fulfill({ status: 201, json: { api_key: key, token: "abk_example_secret" } });
    });
    await page.route("**/api/v1/auth/me/api-keys/*", async (route) => {
      keys = keys.map((key) => ({ ...key, status: "REVOKED", revoked_at: "2026-09-30T10:01:00Z" }));
      await route.fulfill({ status: 204 });
    });
  });

  test("creates, reveals once, and revokes a key", async ({ page }) => {
    await page.goto("/dashboard/account");
    await expect(page.getByRole("heading", { name: "Personal API keys" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Change password" })).toBeVisible();
    await page.getByPlaceholder("My automation").fill("Research agent");
    await page.getByRole("button", { name: "Create key" }).click();
    await expect(page.getByText("abk_example_secret")).toBeVisible();
    await page.getByRole("button", { name: "Done" }).click();
    await expect(page.getByText("abk_example_secret")).toHaveCount(0);
    await expect(page.getByText("Research agent")).toBeVisible();
    await page.getByRole("button", { name: "Revoke", exact: true }).click();
    await page.getByRole("button", { name: "Revoke key" }).click();
    await expect(page.getByText(/revoked/)).toBeVisible();
  });

  test("shows loading and empty states, then retries a failed list", async ({ page }) => {
    let requests = 0;
    await page.route("**/api/v1/auth/me/api-keys", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      requests += 1;
      if (requests === 1) {
        await new Promise((resolve) => setTimeout(resolve, 800));
        await route.fulfill({ json: [] });
      } else if (requests === 2) {
        await route.fulfill({ status: 500, json: { detail: "Temporary failure" } });
      } else {
        await route.fulfill({ json: [] });
      }
    });

    await page.goto("/dashboard/account");
    await expect(page.getByText("Loading keys…")).toBeVisible();
    await expect(page.getByText("No API keys yet.")).toBeVisible();
    await page.reload();
    await expect(page.getByText("Could not load API keys.")).toBeVisible();
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await expect(page.getByText("No API keys yet.")).toBeVisible();
  });

  test("explains when key metadata is forbidden", async ({ page }) => {
    await page.route("**/api/v1/auth/me/api-keys", (route) =>
      route.fulfill({ status: 403, json: { detail: "Forbidden" } }),
    );
    await page.goto("/dashboard/account");
    await expect(page.getByText("You don't have permission to view API keys.")).toBeVisible();
  });
});
