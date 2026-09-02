import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { DataSupport } from "../pages/data-support/data-support.po";
import { SettingsAgentDefaultsPage } from "../pages/settings-agent-defaults.po";
import UserContext from "../fixtures/user-context.json";

/** The default fixture is a platform-admin Owner; Agent Settings is admin-only, so a
 *  Member needs both of those stripped to prove the tab is hidden. */
function memberContext() {
  return {
    ...UserContext,
    is_platform_admin: false,
    organization_users: UserContext.organization_users.map((membership) => ({
      ...membership,
      role: "MEMBER",
    })),
  };
}

test.describe("Settings · Agents", () => {
  test.describe.configure({ mode: "serial" });

  let dataSupport: DataSupport;
  let settings: SettingsAgentDefaultsPage;

  test.use({ storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    dataSupport = new DataSupport(page);
    settings = new SettingsAgentDefaultsPage(page);

    await dataSupport.auth.interceptRefreshRequest();
    await dataSupport.users.interceptGetUserContextRequest();
    await dataSupport.users.interceptGetOrganizationsRequest();
    await dataSupport.organizations.interceptGetOrganization();
    await dataSupport.organizations.interceptAgentSettings();
    await dataSupport.agents.interceptGetModelsRequest();
  });

  test("opens on Agents and reports the platform default", async ({ page }) => {
    await settings.open();

    await expect(settings.heading).toBeVisible();
    await expect(page.getByText("Platform default", { exact: true })).toBeVisible();
    // The two counts are what make a default change legible before it is made.
    await expect(page.getByText("2 Agents", { exact: true })).toBeVisible();
    await expect(page.getByText("1 Agent", { exact: true })).toBeVisible();
  });

  test("naming the blast radius before changing the default", async ({ page }) => {
    await settings.open();
    await settings.editDefaultModel();
    await settings.chooseModel(/gpt-5 mini/i);
    await settings.apply("Change default");

    // The confirmation has to say how many Agents move and that nothing restarts on
    // its own — that is the entire reason it exists.
    await expect(page.getByText(/2 Agents follow the default/i)).toBeVisible();
    await expect(page.getByText(/after their next restart/i)).toBeVisible();
    await expect(page.getByText(/1 Agent has their own model/i)).toBeVisible();
  });

  test("a saved default becomes the organization's own", async ({ page }) => {
    await settings.open();
    await settings.editDefaultModel();
    await settings.chooseModel(/gpt-5 mini/i);
    await settings.apply("Change default");
    await settings.confirm("Change default");

    await expect(page.getByText("This organization", { exact: true })).toBeVisible();
  });

  test("a member never sees the Agents tab", async ({ page }) => {
    await dataSupport.users.interceptGetUserContextRequest({
      userContext: memberContext(),
    });

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings`);

    await expect(page.getByRole("button", { name: "Agents", exact: true })).toHaveCount(0);
    // It falls back to the first section a Member can actually see.
    await expect(page.getByRole("heading", { name: "Templates" })).toBeVisible();
  });
});
