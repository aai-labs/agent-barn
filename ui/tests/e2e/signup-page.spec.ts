import { expect, test } from "@playwright/test";

test.describe("Signup Page", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("should redirect to login", async ({ page }) => {
    await page.goto("/signup");
    await page.waitForURL("/login");
    await expect(page).toHaveURL("/login");
  });
});
