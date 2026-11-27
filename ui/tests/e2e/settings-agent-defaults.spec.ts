import { expect, test } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { DataSupport } from "../pages/data-support/data-support.po";
import { org } from "../pages/data-support/organization-data-support.po";
import { SettingsAgentDefaultsPage } from "../pages/settings-agent-defaults.po";
import UserContext from "../fixtures/user-context.json";

const OFFERED_MODELS = [
  { value: "litellm/openrouter/z-ai/glm-5.2", label: "GLM 5.2", is_default: true },
  { value: "litellm/openrouter/openai/gpt-5-mini", label: "GPT-5 mini" },
];
const ANTHROPIC_SONNET = {
  value: "litellm/anthropic/claude-sonnet-4-5",
  label: "claude-sonnet-4-5",
  connection: "Anthropic",
  pricing: { prompt: "0.000003000000000000", completion: "0.000015000000000000" },
};

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
    await dataSupport.agents.interceptGetModelsRequest({ body: OFFERED_MODELS });
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
    await dataSupport.agents.interceptGetModelsRequest({ body: OFFERED_MODELS });
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
    await expect(section.getByText("GPT-5 mini", { exact: true })).toBeVisible();
    await section.getByRole("button", { name: "Remove Claude Sonnet" }).click();
    await section.getByRole("button", { name: "Add models" }).click();
    const dialog = page.getByRole("dialog", { name: "Add models" });
    await dialog.getByLabel("Search catalog").fill("claude");
    const checkbox = dialog.getByRole("checkbox", { name: "Claude Sonnet" });
    await checkbox.check();
    const checkboxBox = await checkbox.boundingBox();
    const listBox = await checkbox.locator("xpath=../..").boundingBox();
    expect(checkboxBox).not.toBeNull();
    expect(listBox).not.toBeNull();
    expect(checkboxBox!.x + checkboxBox!.width + 3).toBeLessThan(listBox!.x + listBox!.width);
    await dialog.getByRole("button", { name: "Add 1 model" }).click();
    await expect(section.getByText("Claude Sonnet", { exact: true })).toBeVisible();
    await expect(section.getByText("128,000 tokens context")).toBeVisible();
    await expect(section.getByText("Input $2.5 / 1M tokens")).toBeVisible();
    await expect(section.getByText("Output $10 / 1M tokens")).toBeVisible();
  });

  test("keeps unavailable models visible and removable", async ({ page }) => {
    await dataSupport.organizations.interceptGetOrganization({ organization: org({ allowed_models: ["openrouter/openai/gpt-5-mini", "openrouter/nex-agi/nex-n2-pro"] }) });
    await dataSupport.agents.interceptGetModelsRequest({ body: [
      { value: "litellm/openrouter/openai/gpt-5-mini", label: "GPT-5 mini", context_length: 128000, pricing: { prompt: "0.0000025", completion: "0.00001" } },
      { value: "litellm/openrouter/anthropic/claude-sonnet", label: "Claude Sonnet", context_length: 200000, pricing: { prompt: "0.000003", completion: "0.000015" } },
    ] });
    await settings.open();
    const section = page.getByRole("region", { name: "Allowed models" });
    await expect(section.getByText("Not in the OpenRouter catalog")).toHaveCount(1);
    await expect(section.getByText("128,000 tokens context")).toBeVisible();
    await expect(section.getByText("Kept in the allowed list until removed.")).toBeVisible();
    await section.getByRole("button", { name: "Edit" }).click();
    await section.getByRole("button", { name: "Remove nex-agi/nex-n2-pro" }).click();
    await expect(section.getByText("nex-agi/nex-n2-pro")).toHaveCount(0);
    await section.getByRole("button", { name: "Cancel" }).click();
    await expect(section.getByText("nex-agi/nex-n2-pro")).toBeVisible();
  });

  test("a save sends each model as its connection's entry", async ({ page }) => {
    const saved = await dataSupport.organizations.interceptRenameOrganization();
    await dataSupport.agents.interceptGetModelsRequest({ body: OFFERED_MODELS });
    await settings.open();
    const section = page.getByRole("region", { name: "Allowed models" });
    await section.getByRole("button", { name: "Edit" }).click();
    await section.getByRole("button", { name: "Remove GPT-5 mini" }).click();
    await section.getByRole("button", { name: "Save models" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Save models" }).click();
    await expect.poll(() => saved.payload).toEqual({ allowed_models: ["openrouter/z-ai/glm-5.2"] });
  });

  test("an OpenRouter glob still expands to the catalog's models", async ({ page }) => {
    await dataSupport.organizations.interceptGetOrganization({ organization: org({ allowed_models: ["openrouter/openai/*"] }) });
    await dataSupport.agents.interceptGetModelsRequest({ body: [
      { value: "litellm/openrouter/openai/gpt-5-mini", label: "GPT-5 mini", context_length: 128000, pricing: { prompt: "0.0000025", completion: "0.00001" } },
      { value: "litellm/openrouter/anthropic/claude-sonnet", label: "Claude Sonnet", context_length: 200000, pricing: { prompt: "0.000003", completion: "0.000015" } },
    ] });
    await settings.open();
    const section = page.getByRole("region", { name: "Allowed models" });
    await expect(section.getByText("GPT-5 mini", { exact: true })).toBeVisible();
    await expect(section.getByText("Claude Sonnet", { exact: true })).toHaveCount(0);
    await expect(section.getByText("Not in the OpenRouter catalog")).toHaveCount(0);
  });

  test("shows the reason when an allowed model cannot be removed", async ({ page }) => {
    await dataSupport.organizations.interceptRenameOrganization({
      status: 409,
      detail: "1 Agent is still pinned to 'openai/gpt-5-mini': Staging. Point them at an allowed model before removing it.",
    });
    await dataSupport.agents.interceptGetModelsRequest({ body: OFFERED_MODELS });
    await settings.open();
    const section = page.getByRole("region", { name: "Allowed models" });
    await section.getByRole("button", { name: "Edit" }).click();
    await section.getByRole("button", { name: "Remove GPT-5 mini" }).click();
    await section.getByRole("button", { name: "Save models" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Save models" }).click();
    const alert = section.getByRole("alert");
    await expect(alert.getByText("Could not save allowed models")).toBeVisible();
    await expect(alert).toContainText("1 Agent is still pinned to");
    await expect(alert).toContainText("openai/gpt-5-mini");
    await expect(alert).toContainText("Staging");
  });

  test("the default picker lists a value it no longer offers on top, then each connection", async ({ page }) => {
    await dataSupport.agents.interceptGetModelsRequest({ body: [
      { value: "litellm/openrouter/openai/gpt-5-mini", label: "GPT-5 mini", connection: "OpenRouter" },
      ANTHROPIC_SONNET,
    ] });
    await settings.open();
    await settings.editDefaultModel();
    await page.getByRole("button", { name: "Default model" }).click();

    const menu = page.getByRole("listbox");
    await expect(menu.locator(":scope > [role=option]")).toHaveText(["litellm/openrouter/z-ai/glm-5.2"]);
    expect(await menu.getByRole("group").evaluateAll((groups) => groups.map((group) => group.getAttribute("aria-label")))).toEqual(["OpenRouter", "Anthropic"]);
  });

  test("an allowed model of another connection shows its provider and prices, and the catalog groups by connection", async ({ page }) => {
    const saved = await dataSupport.organizations.interceptRenameOrganization();
    await dataSupport.organizations.interceptGetOrganization({ organization: org({ allowed_models: ["openrouter/openai/gpt-5-mini", "anthropic/claude-sonnet-4-5"] }) });
    await dataSupport.agents.interceptGetModelsRequest({ body: [
      { value: "litellm/openrouter/openai/gpt-5-mini", label: "GPT-5 mini", connection: "OpenRouter", context_length: 128000, pricing: { prompt: "0.0000025", completion: "0.00001" } },
      ANTHROPIC_SONNET,
      { value: "litellm/anthropic/claude-haiku-4-5", label: "claude-haiku-4-5", connection: "Anthropic", pricing: { prompt: "0.000001000000000000", completion: "0.000005000000000000" } },
    ] });
    await settings.open();
    const section = page.getByRole("region", { name: "Allowed models" });
    const card = section.locator("[data-slot=card]").filter({ hasText: "claude-sonnet-4-5" });
    await expect(card.getByText("anthropic", { exact: true })).toBeVisible();
    await expect(card.getByText("Input $3 / 1M tokens")).toBeVisible();
    await expect(card.getByText("Output $15 / 1M tokens")).toBeVisible();
    await expect(section.getByText("Not in the OpenRouter catalog")).toHaveCount(0);

    await section.getByRole("button", { name: "Edit" }).click();
    await section.getByRole("button", { name: "Add models" }).click();
    const dialog = page.getByRole("dialog", { name: "Add models" });
    expect(await dialog.getByRole("group").evaluateAll((groups) => groups.map((group) => group.getAttribute("aria-label")))).toEqual(["OpenRouter", "Anthropic"]);
    await dialog.getByLabel("Search catalog").fill("claude");
    await expect(dialog.getByRole("group")).toHaveCount(1);
    await dialog.getByRole("group", { name: "Anthropic" }).getByRole("checkbox", { name: "claude-haiku-4-5" }).check();
    await dialog.getByRole("button", { name: "Add 1 model" }).click();
    await section.getByRole("button", { name: "Save models" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Save models" }).click();
    await expect.poll(() => saved.payload).toEqual({
      allowed_models: ["openrouter/openai/gpt-5-mini", "anthropic/claude-sonnet-4-5", "anthropic/claude-haiku-4-5"],
    });
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
