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

test.describe("Settings · Models", () => {
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

  test("opens on Models and reports the platform default", async ({ page }) => {
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

  test("shows model cards with catalog information", async ({ page }) => {
    await dataSupport.agents.interceptGetModelsRequest({ body: [
      { value: "litellm/openrouter/openai/gpt-5-mini", label: "GPT-5 mini", context_length: 128000, pricing: { prompt: "0.0000025", completion: "0.00001" } },
      { value: "litellm/openrouter/anthropic/claude-sonnet", label: "Claude Sonnet", context_length: 200000, pricing: { prompt: "0.000003", completion: "0.000015" } },
      { value: "litellm/openrouter/google/gemini-pro", label: "Gemini Pro", context_length: 1000000, pricing: { prompt: "0.00000125", completion: "0.000005" } },
      { value: "litellm/openrouter/deepseek/deepseek-chat", label: "DeepSeek Chat", context_length: 64000, pricing: { prompt: "0.0000002", completion: "0.0000004" } },
    ] });
    await settings.open();
    const section = page.getByRole("region", { name: "Allowed models" });
    await section.getByRole("button", { name: "Edit" }).click();
    await expect(section.getByRole("checkbox", { name: "GPT-5 mini" })).toBeChecked();
    await expect(section.getByText("128,000 tokens context")).toBeVisible();
    await expect(section.getByText("Input $2.5 / 1M tokens")).toBeVisible();
    await expect(section.getByText("Output $10 / 1M tokens")).toBeVisible();
  });

  test("a member never sees the Models tab", async ({ page }) => {
    await dataSupport.users.interceptGetUserContextRequest({
      userContext: memberContext(),
    });

    await page.goto(`/dashboard/${TEST_ORG_ID}/settings`);

    await expect(page.getByRole("complementary").getByRole("link", { name: "Models", exact: true })).toHaveCount(0);
    // It falls back to the first section a Member can actually see.
    await expect(page.getByRole("heading", { name: "Templates" })).toBeVisible();
  });
});
