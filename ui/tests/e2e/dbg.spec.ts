import { TEST_ORG_ID } from "../constants";
import { test } from "@playwright/test";
import { DataSupport } from "../pages/data-support/data-support.po";
test.use({ storageState: { cookies: [], origins: [] } });
test("probe", async ({ page }) => {
  const d = new DataSupport(page);
  await d.auth.interceptRefreshRequest();
  await d.users.interceptGetUserContextRequest();
  await d.users.interceptGetOrganizationsRequest();
  await d.organizations.interceptAgentSettings();
  await d.orgTemplates.interceptGetLineages();
  await d.orgTemplates.interceptGetOrgSkills();
  await d.orgTemplates.interceptGetVersions();
  await d.orgTemplates.interceptGetDraft({ status: 404 });
  await page.goto(`/dashboard/${TEST_ORG_ID}/settings/templates/my-custom`);
  await page.waitForTimeout(3000);
  console.log("MARK pulse=" + await page.locator(".animate-pulse").count()
    + " main=" + (await page.locator("main").innerHTML()).length
    + " head=" + await page.locator("h1").count());
});
