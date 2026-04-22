import { test as setup } from "@playwright/test";

setup("auth setup: open login page", async ({ page }) => {
  await page.goto("/login");
});
