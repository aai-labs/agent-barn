import { expect, Page, test } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { DataSupport } from "../pages/data-support/data-support.po";
import {
  ANTHROPIC_CONNECTION,
  AZURE_CONNECTION,
  PlatformLlmProviderDataSupport,
  SAVED_KEY,
} from "../pages/data-support/platform-llm-provider-data-support.po";
import { PlatformLlmProvidersPage } from "../pages/platform-llm-providers-page.po";

const NEW_KEY = "sk-or-v1-replacement-key-c3d4";
const PROVIDER_KEY = "sk-proj-new-provider-key-g7h8";

test.use({ storageState: { cookies: [], origins: [] } });

async function signIn(page: Page, admin = true) {
  const data = new DataSupport(page);
  await data.auth.interceptRefreshRequest();
  await data.users.interceptGetUserContextRequest({ userContext: { ...UserContext, is_platform_admin: admin } });
  await data.users.interceptGetOrganizationsRequest();
}

test("Platform Admin replaces the OpenRouter key and sees only its last four characters", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept();
  await new DataSupport(page).platformMemory.intercept();
  const settings = new PlatformLlmProvidersPage(page);
  await page.goto("/dashboard/platform/settings");
  await page.getByRole("complementary").getByRole("link", { name: "LLM providers", exact: true }).click();

  await expect(settings.card()).toContainText("sk-*******a1b2");
  await expect(settings.card()).toContainText("Platform Person");
  await expect(settings.card()).not.toContainText("OPENROUTER_API_KEY");

  await settings.openDialogButton().click();
  await expect(settings.keyInput()).toHaveAttribute("type", "password");
  await settings.keyInput().fill(`  ${NEW_KEY}  `);
  await settings.dialog().getByRole("button", { name: "Save key" }).click();

  await expect(settings.dialog()).toHaveCount(0);
  await expect(page.getByRole("status")).toHaveText("OpenRouter key saved.");
  await expect(settings.card()).toContainText("sk-*******c3d4");
  await expect(page.getByText(NEW_KEY)).toHaveCount(0);
  expect(mock.writes).toEqual([{ api_key: NEW_KEY }]);
  await page.screenshot({ path: test.info().outputPath("platform-llm-providers.png"), fullPage: true });
});

test("the environment key is named while it is the one Agents use", async ({ page }) => {
  await signIn(page);
  await new PlatformLlmProviderDataSupport(page).intercept({
    connection: { has_api_key: false, api_key_last4: null, updated_at: null, updated_by: null, env_key_configured: true },
  });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await expect(settings.card()).toContainText("No key saved");
  await expect(settings.card()).toContainText("Agents use OPENROUTER_API_KEY from this deployment's secrets");
  await expect(settings.openDialogButton()).toHaveText("Save a key");
});

test("a deployment with no key at all says Agents cannot call OpenRouter", async ({ page }) => {
  await signIn(page);
  await new PlatformLlmProviderDataSupport(page).intercept({
    connection: { has_api_key: false, api_key_last4: null, updated_at: null, updated_by: null, env_key_configured: false },
  });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await expect(settings.card()).toContainText("Agents cannot call OpenRouter models until a key is saved.");
});

test("a saved key warns while the deployment still sets OPENROUTER_API_KEY", async ({ page }) => {
  await signIn(page);
  await new PlatformLlmProviderDataSupport(page).intercept({ connection: { ...SAVED_KEY, env_key_configured: true } });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await expect(settings.card().getByRole("note")).toContainText("OPENROUTER_API_KEY is still set");
});

test("a key OpenRouter refuses keeps the dialog open and the saved key unchanged", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept({ saveStatus: 422 });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await settings.submitKey(NEW_KEY);

  await expect(settings.dialog().getByRole("alert")).toHaveText(
    "OpenRouter did not accept this key. Your key was not changed.",
  );
  await expect(settings.keyInput()).toHaveValue(NEW_KEY);
  await settings.cancelDialog();
  await expect(settings.card()).toContainText("sk-*******a1b2");
  expect(mock.writes).toHaveLength(1);
});

test("an empty key is not sent", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept();
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await settings.submitKey("   ");

  await expect(settings.dialog().getByRole("alert")).toHaveText("Paste the key from your OpenRouter dashboard.");
  expect(mock.writes).toEqual([]);
});

test("Organization Owner cannot fetch or change the OpenRouter key", async ({ page }) => {
  await signIn(page, false);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept();
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await expect(page.getByText("Platform admin access required")).toBeVisible();
  await expect(settings.card()).toHaveCount(0);
  expect(mock.reads).toEqual([]);
  expect(mock.writes).toEqual([]);
  expect(mock.adds).toEqual([]);
});

test("a failed status read can be retried", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept({ readStatus: 503 });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await expect(page.getByText("Could not load LLM provider settings")).toBeVisible();
  mock.recover();
  await page.getByRole("button", { name: /retry|try again/i }).click();
  await expect(settings.card()).toContainText("sk-*******a1b2");
});

test("Platform Admin sees every other connection with only its last four characters", async ({ page }) => {
  await signIn(page);
  await new PlatformLlmProviderDataSupport(page).intercept({ connections: [ANTHROPIC_CONNECTION, AZURE_CONNECTION] });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await expect(settings.card()).toContainText("sk-*******a1b2");
  await expect(settings.providerCardNames()).toHaveText(["Anthropic", "Azure Europe"]);
  await expect(settings.providerCard("Anthropic")).toContainText("*******c3d4");
  await expect(settings.providerCard("Anthropic")).not.toContainText("sk-");
  await expect(settings.providerCard("Anthropic")).toContainText("Changed by Platform Person");
  await expect(settings.providerCard("Azure Europe")).toContainText("Azure");
  await expect(settings.providerCard("Azure Europe")).toContainText("https://contoso.openai.azure.com");
  await expect(settings.providerCard("Azure Europe")).toContainText("*******e5f6");
});

test("a platform with only OpenRouter says no other provider is connected", async ({ page }) => {
  await signIn(page);
  await new PlatformLlmProviderDataSupport(page).intercept();
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await expect(settings.otherProviders()).toContainText("No other provider is connected.");
  await expect(settings.providerCardNames()).toHaveCount(0);
});

test("Platform Admin adds a known provider and sees only its last four characters", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept({ connections: [ANTHROPIC_CONNECTION] });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await settings.addProviderButton().click();
  await settings.providerSelect().click();
  await expect(settings.providerOptions()).toHaveText([
    "OpenAI",
    "Gemini",
    "xAI",
    "DeepSeek",
    "Fireworks",
    "Novita",
    "Azure",
    "Custom (OpenAI-compatible)",
  ]);
  await page.getByRole("option", { name: "OpenAI", exact: true }).click();
  await expect(settings.slugInput()).toHaveCount(0);
  await expect(settings.baseUrlInput()).toHaveCount(0);
  await expect(settings.apiKeyInput()).toHaveAttribute("type", "password");
  await settings.apiKeyInput().fill(`  ${PROVIDER_KEY}  `);
  await settings.dialog().getByRole("button", { name: "Add provider" }).click();

  await expect(settings.dialog()).toHaveCount(0);
  await expect(settings.otherProviders().getByRole("status")).toHaveText("OpenAI added.");
  await expect(settings.providerCard("OpenAI")).toContainText("*******g7h8");
  await expect(page.getByText(PROVIDER_KEY)).toHaveCount(0);
  expect(mock.adds).toEqual([{ provider_type: "openai", api_key: PROVIDER_KEY }]);
});

test("Platform Admin adds an Azure connection with its name, slug and base URL", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept();
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await settings.addProvider({
    provider: "Azure",
    name: " Azure Europe ",
    slug: " azure-eu ",
    baseUrl: " https://contoso.openai.azure.com/ ",
    key: PROVIDER_KEY,
  });

  await expect(settings.dialog()).toHaveCount(0);
  await expect(settings.otherProviders().getByRole("status")).toHaveText("Azure Europe added.");
  await expect(settings.providerCard("Azure Europe")).toContainText("https://contoso.openai.azure.com");
  await expect(settings.providerCard("Azure Europe")).toContainText("*******g7h8");
  expect(mock.adds).toEqual([
    {
      provider_type: "azure",
      name: "Azure Europe",
      slug: "azure-eu",
      base_url: "https://contoso.openai.azure.com/",
      api_key: PROVIDER_KEY,
    },
  ]);
});

test("a key the provider refuses keeps the add dialog open with the API's message", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept({
    addStatus: 422,
    addDetail: "Anthropic did not accept this key. Nothing was saved.",
  });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await settings.addProvider({ provider: "Anthropic", key: PROVIDER_KEY });

  await expect(settings.dialog().getByRole("alert")).toHaveText("Anthropic did not accept this key. Nothing was saved.");
  await expect(settings.apiKeyInput()).toHaveValue(PROVIDER_KEY);
  await settings.cancelDialog();
  await expect(settings.providerCard("Anthropic")).toHaveCount(0);
  expect(mock.adds).toHaveLength(1);
});

test("a Custom slug the API refuses shows its message", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept({
    addStatus: 422,
    addDetail: "The slug can't be a provider's name.",
  });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await settings.addProvider({
    provider: "Custom (OpenAI-compatible)",
    name: "Lab",
    slug: "openai",
    baseUrl: "https://lab.example.com/v1",
    key: PROVIDER_KEY,
  });

  await expect(settings.dialog().getByRole("alert")).toHaveText("The slug can't be a provider's name.");
  await expect(settings.slugInput()).toHaveValue("openai");
  expect(mock.adds).toHaveLength(1);
});

test("a provider is not added without a choice or a key", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept();
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await settings.addProvider({ key: PROVIDER_KEY });
  await expect(settings.dialog().getByRole("alert")).toHaveText("Choose a provider.");

  await settings.chooseProvider("OpenAI");
  await settings.apiKeyInput().fill("   ");
  await settings.dialog().getByRole("button", { name: "Add provider" }).click();
  await expect(settings.dialog().getByRole("alert")).toHaveText("Paste the provider's API key.");
  expect(mock.adds).toEqual([]);
});

test("a failed read of the other providers can be retried", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept({
    listStatus: 503,
    connections: [ANTHROPIC_CONNECTION],
  });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await expect(settings.card()).toContainText("sk-*******a1b2");
  await expect(page.getByText("Could not load the other LLM providers")).toBeVisible();
  mock.recover();
  await page.getByRole("button", { name: /retry|try again/i }).click();
  await expect(settings.providerCard("Anthropic")).toContainText("*******c3d4");
});
