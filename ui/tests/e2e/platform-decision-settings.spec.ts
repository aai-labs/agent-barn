import { expect, test } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { DataSupport } from "../pages/data-support/data-support.po";
import { PlatformDecisionSettingsPage } from "../pages/platform-decision-settings-page.po";

test.use({ storageState: { cookies: [], origins: [] } });

test("a Platform Administrator chooses the decision model", async ({ page }) => {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest({ userContext: { ...UserContext, is_platform_admin: true } });
  await data.users.interceptGetOrganizationsRequest();
  const settings = await data.decisions.interceptPlatformSettings();
  const decisions = new PlatformDecisionSettingsPage(page);
  await decisions.goto();

  await expect(decisions.tab()).toBeVisible();
  await expect(decisions.modelSummary()).toContainText("jev");
  await decisions.chooseModel("openai (openai/gpt-6-luna-decisions)");

  await expect(page.getByRole("status")).toContainText("Decision model saved");
  expect(settings.writes).toEqual([{ model: "openai" }]);
});
