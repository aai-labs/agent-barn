import { expect, Page, test } from "@playwright/test";

import UserContext from "../fixtures/user-context.json";
import { DataSupport } from "../pages/data-support/data-support.po";
import {
  ANTHROPIC_CONNECTION,
  ANTHROPIC_STORED_MODELS,
  AZURE_CATALOGUE,
  AZURE_CONNECTION,
  AZURE_DEPLOYMENTS,
  CUSTOM_CATALOGUE,
  CUSTOM_CONNECTION,
  CUSTOM_MODELS,
  DROPPED_MODEL,
  PlatformLlmProviderDataSupport,
  pricedCatalogue,
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
  await expect(settings.toast("OpenRouter key saved")).toBeVisible();
  await expect(settings.providerList()).not.toContainText("key saved");
  await expect(settings.card()).toContainText("sk-*******c3d4");
  await expect(page.getByText(NEW_KEY)).toHaveCount(0);
  expect(mock.writes).toEqual([{ slug: "openrouter", body: { api_key: NEW_KEY } }]);
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
  expect(mock.deletes).toEqual([]);
});

test("a failed read can be retried", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept({
    listStatus: 503,
    connections: [ANTHROPIC_CONNECTION],
  });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await expect(page.getByText("Could not load LLM provider settings")).toBeVisible();
  mock.recover();
  await page.getByRole("button", { name: /retry|try again/i }).click();
  await expect(settings.card()).toContainText("sk-*******a1b2");
  await expect(settings.providerCard("Anthropic")).toContainText("*******c3d4");
});

test("Platform Admin sees every connection in its own card with only its last four characters", async ({ page }) => {
  await signIn(page);
  await new PlatformLlmProviderDataSupport(page).intercept({ connections: [ANTHROPIC_CONNECTION, AZURE_CONNECTION] });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await expect(settings.card()).toContainText("sk-*******a1b2");
  await expect(settings.providerCardNames()).toHaveText(["OpenRouter", "Anthropic", "Azure Europe"]);
  await expect(settings.providerCard("Anthropic")).toContainText("*******c3d4");
  await expect(settings.providerCard("Anthropic")).not.toContainText("sk-");
  await expect(settings.providerCard("Anthropic")).toContainText("Changed by Platform Person");
  await expect(settings.providerCard("Azure Europe")).toContainText("Azure");
  await expect(settings.providerCard("Azure Europe")).toContainText("https://contoso.openai.azure.com");
  await expect(settings.providerCard("Azure Europe")).toContainText("*******e5f6");
});

test("a platform with only OpenRouter lists OpenRouter, with Add provider outside every card", async ({ page }) => {
  await signIn(page);
  await new PlatformLlmProviderDataSupport(page).intercept();
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await expect(settings.providerCardNames()).toHaveText(["OpenRouter"]);
  await expect(settings.addProviderButton()).toBeVisible();
  await expect(settings.providerList().getByRole("button", { name: "Add provider" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Other providers" })).toHaveCount(0);
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
  await expect(settings.toast("OpenAI added")).toBeVisible();
  await expect(settings.providerList()).not.toContainText("added");
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
  await expect(settings.toast("Azure Europe added")).toBeVisible();
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

test("Platform Admin replaces a known provider's key", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept({ connections: [ANTHROPIC_CONNECTION] });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await settings.replaceKeyButton("Anthropic").click();
  await expect(settings.dialog().getByRole("heading", { name: "Replace the Anthropic key" })).toBeVisible();
  await expect(settings.baseUrlInput()).toHaveCount(0);
  await expect(settings.keyInput("Anthropic")).toHaveAttribute("type", "password");
  await settings.keyInput("Anthropic").fill(`  ${PROVIDER_KEY}  `);
  await settings.dialog().getByRole("button", { name: "Save key" }).click();

  await expect(settings.dialog()).toHaveCount(0);
  await expect(settings.toast("Anthropic key saved")).toBeVisible();
  await expect(settings.providerList()).not.toContainText("key saved");
  await expect(settings.providerCard("Anthropic")).toContainText("*******g7h8");
  await expect(page.getByText(PROVIDER_KEY)).toHaveCount(0);
  expect(mock.writes).toEqual([{ slug: "anthropic", body: { api_key: PROVIDER_KEY } }]);
});

test("an Azure key is replaced at its stored base URL unless a new one is entered", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept({ connections: [AZURE_CONNECTION] });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await settings.replaceKeyButton("Azure Europe").click();
  await expect(settings.baseUrlInput()).toHaveValue("https://contoso.openai.azure.com");
  await settings.keyInput("Azure Europe").fill(PROVIDER_KEY);
  await settings.dialog().getByRole("button", { name: "Save key" }).click();
  await expect(settings.dialog()).toHaveCount(0);

  await settings.replaceKey("Azure Europe", { key: PROVIDER_KEY, baseUrl: " https://fabrikam.openai.azure.com/ " });

  await expect(settings.dialog()).toHaveCount(0);
  await expect(settings.providerCard("Azure Europe")).toContainText("https://fabrikam.openai.azure.com");
  expect(mock.writes).toEqual([
    { slug: "azure-eu", body: { api_key: PROVIDER_KEY } },
    { slug: "azure-eu", body: { api_key: PROVIDER_KEY, base_url: "https://fabrikam.openai.azure.com/" } },
  ]);
});

test("a refused replacement keeps the dialog open and the saved key unchanged", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept({
    connections: [AZURE_CONNECTION],
    saveStatus: 422,
    saveDetail: "The base URL did not answer like a model API. Nothing was saved.",
  });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await settings.replaceKey("Azure Europe", { key: PROVIDER_KEY, baseUrl: "https://www.example.com" });

  await expect(settings.dialog().getByRole("alert")).toHaveText(
    "The base URL did not answer like a model API. Nothing was saved.",
  );
  await expect(settings.keyInput("Azure Europe")).toHaveValue(PROVIDER_KEY);
  await settings.cancelDialog();
  await expect(settings.providerCard("Azure Europe")).toContainText("*******e5f6");
  await expect(settings.providerCard("Azure Europe")).toContainText("https://contoso.openai.azure.com");
  expect(mock.writes).toHaveLength(1);
});

test("Platform Admin deletes a connection only after confirming", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept({
    connections: [ANTHROPIC_CONNECTION, AZURE_CONNECTION],
  });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await settings.deleteButton("Anthropic").click();
  await expect(settings.dialog().getByRole("heading", { name: "Delete Anthropic?" })).toBeVisible();
  await settings.cancelDialog();
  expect(mock.deletes).toEqual([]);
  await expect(settings.providerCard("Anthropic")).toHaveCount(1);

  await settings.deleteButton("Anthropic").click();
  await settings.confirmDelete();

  await expect(settings.dialog()).toHaveCount(0);
  await expect(settings.providerCard("Anthropic")).toHaveCount(0);
  await expect(settings.toast("Anthropic deleted")).toBeVisible();
  await expect(settings.providerCardNames()).toHaveText(["OpenRouter", "Azure Europe"]);
  expect(mock.deletes).toEqual(["anthropic"]);
  await settings.addProviderButton().click();
  await settings.providerSelect().click();
  await expect(page.getByRole("option", { name: "Anthropic", exact: true })).toBeVisible();
});

test("deleting an Azure connection warns that its slug can't be used again", async ({ page }) => {
  await signIn(page);
  await new PlatformLlmProviderDataSupport(page).intercept({ connections: [AZURE_CONNECTION] });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await settings.deleteButton("Azure Europe").click();

  await expect(settings.dialog()).toContainText("azure-eu can't be used again");
});

test("a refused delete keeps the confirmation open with the API's message", async ({ page }) => {
  await signIn(page);
  const mock = await new PlatformLlmProviderDataSupport(page).intercept({
    connections: [ANTHROPIC_CONNECTION],
    deleteStatus: 404,
    deleteDetail: "That connection does not exist.",
  });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await settings.deleteButton("Anthropic").click();
  await settings.confirmDelete();

  await expect(settings.dialog().getByRole("alert")).toHaveText("That connection does not exist.");
  expect(mock.deletes).toEqual(["anthropic"]);
});

test("OpenRouter can't be deleted", async ({ page }) => {
  await signIn(page);
  await new PlatformLlmProviderDataSupport(page).intercept({ connections: [ANTHROPIC_CONNECTION] });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await expect(settings.deleteButton("Anthropic")).toBeVisible();
  await expect(settings.card().getByRole("button", { name: "Delete" })).toHaveCount(0);
});

type ModelsOptions = Parameters<PlatformLlmProviderDataSupport["interceptModels"]>[0];

async function openAnthropicModels(page: Page, models: ModelsOptions = {}) {
  await signIn(page);
  const data = new PlatformLlmProviderDataSupport(page);
  await data.intercept({ connections: [ANTHROPIC_CONNECTION] });
  const mock = await data.interceptModels(models);
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();
  await settings.modelsButton("Anthropic").click();
  return { mock, settings };
}

test("Platform Admin ticks a model priced by LiteLLM and saves, keeping the stored models' prices", async ({ page }) => {
  const { mock, settings } = await openAnthropicModels(page);

  await expect(settings.dialog().getByRole("heading", { name: "Anthropic models" })).toBeVisible();
  await expect(settings.dialog().getByRole("columnheader")).toHaveText([
    "Model",
    "Input",
    "Output",
    "Cache read",
    "Cache write",
  ]);
  await expect(settings.modelCells("claude-haiku-4-5")).toHaveText(["claude-haiku-4-5", "$1", "$5", "$0.1", "$1.25"]);
  await expect(settings.modelCheckbox("claude-haiku-4-5")).not.toBeChecked();
  await expect(settings.modelCells("claude-sonnet-4-5")).toHaveText([
    "claude-sonnet-4-5",
    "$3",
    "$15",
    "$0.3",
    "$3.75",
  ]);
  await expect(settings.modelCheckbox("claude-sonnet-4-5")).toBeChecked();
  await expect(settings.modelCells("claude-opus-4-1")).toHaveText([
    "claude-opus-4-1LiteLLM's price has changedUse LiteLLM's price",
    "$12LiteLLM $15",
    "$60LiteLLM $75",
    "$1.5",
    "$15LiteLLM $18.75",
  ]);
  await expect(settings.modelCheckbox("claude-opus-4-1")).toBeChecked();
  await expect(settings.tickedCount()).toHaveText("2 of 50 ticked");

  await settings.modelCheckbox("claude-haiku-4-5").click();
  await expect(settings.tickedCount()).toHaveText("3 of 50 ticked");
  await settings.saveModels();

  await expect(settings.dialog()).toHaveCount(0);
  await expect(settings.toast("Anthropic models saved")).toBeVisible();
  expect(mock.saves).toEqual([
    {
      slug: "anthropic",
      body: {
        models: [
          { model_id: "claude-haiku-4-5", price: "litellm" },
          { model_id: "claude-opus-4-1", price: "stored" },
          { model_id: "claude-sonnet-4-5", price: "stored" },
        ],
      },
    },
  ]);
});

test("unticking a stored model removes it on save", async ({ page }) => {
  const { mock, settings } = await openAnthropicModels(page);

  await settings.modelCheckbox("claude-opus-4-1").click();
  await settings.saveModels();

  await expect(settings.toast("Anthropic models saved")).toBeVisible();
  expect(mock.saves.map((save) => save.body)).toEqual([
    { models: [{ model_id: "claude-sonnet-4-5", price: "stored" }] },
  ]);
});

test("a model LiteLLM has no price for is ticked with typed prices per 1M tokens", async ({ page }) => {
  const { mock, settings } = await openAnthropicModels(page);

  await expect(settings.modelCells("claude-unpriced-preview")).toHaveText([
    "claude-unpriced-preview",
    "LiteLLM has no price for this model; tick it to type its prices.",
  ]);
  await settings.modelCheckbox("claude-unpriced-preview").click();
  await expect(settings.saveModelsButton()).toBeDisabled();
  await settings.typePrices("claude-unpriced-preview", ["1.5", "6", "0.15", "0"]);
  await settings.saveModels();

  await expect(settings.toast("Anthropic models saved")).toBeVisible();
  expect(mock.saves.map((save) => save.body)).toEqual([
    {
      models: [
        { model_id: "claude-opus-4-1", price: "stored" },
        { model_id: "claude-sonnet-4-5", price: "stored" },
        {
          model_id: "claude-unpriced-preview",
          price: {
            input_cost_per_token: "0.0000015",
            output_cost_per_token: "0.000006",
            cache_read_input_token_cost: "0.00000015",
            cache_creation_input_token_cost: "0",
          },
        },
      ],
    },
  ]);
});

test("a stored model whose LiteLLM price changed is saved at LiteLLM's price once accepted", async ({ page }) => {
  const { mock, settings } = await openAnthropicModels(page);

  await expect(settings.useLiteLLMPriceButton("claude-sonnet-4-5")).toHaveCount(0);
  await settings.useLiteLLMPriceButton("claude-opus-4-1").click();

  await expect(settings.modelCells("claude-opus-4-1")).toHaveText([
    "claude-opus-4-1Takes LiteLLM's price when saved",
    "$15",
    "$75",
    "$1.5",
    "$18.75",
  ]);
  expect(mock.saves).toEqual([]);
  await settings.saveModels();

  await expect(settings.toast("Anthropic models saved")).toBeVisible();
  expect(mock.saves.map((save) => save.body)).toEqual([
    {
      models: [
        { model_id: "claude-opus-4-1", price: "litellm" },
        { model_id: "claude-sonnet-4-5", price: "stored" },
      ],
    },
  ]);
});

test("the filter narrows the models by id", async ({ page }) => {
  const { settings } = await openAnthropicModels(page);

  await settings.modelFilter().fill("SONNET");

  await expect(settings.modelCheckboxes()).toHaveCount(1);
  await expect(settings.modelCheckbox("claude-sonnet-4-5")).toBeVisible();
});

test("at 50 ticked models the rest can't be ticked", async ({ page }) => {
  const { settings } = await openAnthropicModels(page, pricedCatalogue(51, 50));

  await expect(settings.tickedCount()).toHaveText("50 of 50 ticked");
  await expect(settings.modelCheckbox("model-50")).toBeDisabled();
  await settings.modelCheckbox("model-00").click();
  await expect(settings.modelCheckbox("model-50")).toBeEnabled();
});

test("Select all priced ticks every model LiteLLM prices and saves them at LiteLLM's price", async ({ page }) => {
  const { mock, settings } = await openAnthropicModels(page);

  await settings.selectAllPricedButton().click();

  await expect(settings.modelCheckbox("claude-haiku-4-5")).toBeChecked();
  await expect(settings.modelCheckbox("claude-unpriced-preview")).not.toBeChecked();
  await expect(settings.tickedCount()).toHaveText("3 of 50 ticked");
  await expect(settings.selectAllPricedButton()).toBeDisabled();
  await settings.saveModels();

  await expect(settings.toast("Anthropic models saved")).toBeVisible();
  expect(mock.saves.map((save) => save.body)).toEqual([
    {
      models: [
        { model_id: "claude-haiku-4-5", price: "litellm" },
        { model_id: "claude-opus-4-1", price: "stored" },
        { model_id: "claude-sonnet-4-5", price: "stored" },
      ],
    },
  ]);
});

test("Select all priced ticks only the models the filter shows", async ({ page }) => {
  const { settings } = await openAnthropicModels(page, pricedCatalogue(12, 0));

  await settings.modelFilter().fill("model-1");
  await settings.selectAllPricedButton().click();
  await settings.modelFilter().fill("");

  await expect(settings.tickedCount()).toHaveText("2 of 50 ticked");
  await expect(settings.modelCheckbox("model-10")).toBeChecked();
  await expect(settings.modelCheckbox("model-11")).toBeChecked();
  await expect(settings.modelCheckbox("model-01")).not.toBeChecked();
});

test("Select all priced stops at 50 models and says how many it left unticked", async ({ page }) => {
  const { settings } = await openAnthropicModels(page, pricedCatalogue(60, 10));

  await settings.selectAllPricedButton().click();

  await expect(settings.tickedCount()).toHaveText("50 of 50 ticked");
  await expect(settings.modelCheckbox("model-49")).toBeChecked();
  await expect(settings.modelCheckbox("model-50")).not.toBeChecked();
  await expect(settings.dialog()).toContainText("The 50-model limit left 10 priced models unticked.");
  await expect(settings.selectAllPricedButton()).toBeDisabled();
});

test("a refused save keeps the dialog open with the API's message", async ({ page }) => {
  const { mock, settings } = await openAnthropicModels(page, {
    saveStatus: 422,
    saveDetail: "Anthropic does not list one of these models. Nothing was saved.",
  });

  await settings.modelCheckbox("claude-haiku-4-5").click();
  await settings.saveModels();

  await expect(settings.dialog().getByRole("alert")).toHaveText(
    "Anthropic does not list one of these models. Nothing was saved.",
  );
  await expect(settings.modelCheckbox("claude-haiku-4-5")).toBeChecked();
  expect(mock.saves).toHaveLength(1);
});

test("a model list the provider refuses shows the API's message and can be retried", async ({ page }) => {
  const { mock, settings } = await openAnthropicModels(page, {
    catalogueStatus: 409,
    catalogueDetail: "Anthropic did not accept the stored key. Replace the key, then try again.",
  });

  await expect(settings.dialog().getByRole("alert")).toHaveText(
    "Anthropic did not accept the stored key. Replace the key, then try again.",
  );
  await expect(settings.modelCheckboxes()).toHaveCount(0);
  mock.recover();
  await settings.dialog().getByRole("button", { name: "Retry" }).click();

  await expect(settings.modelCheckbox("claude-sonnet-4-5")).toBeChecked();
  expect(mock.catalogueReads.length).toBeGreaterThan(1);
});

test("a stored model the provider no longer lists is shown as removed and left out of the save", async ({ page }) => {
  const { mock, settings } = await openAnthropicModels(page, { models: [...ANTHROPIC_STORED_MODELS, DROPPED_MODEL] });

  await expect(settings.modelsNoLongerListed()).toContainText("No longer listed by Anthropic. Saving removes them.");
  await expect(settings.modelsNoLongerListed()).toContainText("claude-3-opus-20240229");
  await expect(settings.modelCheckbox("claude-3-opus-20240229")).toHaveCount(0);
  await settings.saveModels();

  await expect(settings.toast("Anthropic models saved")).toBeVisible();
  expect(mock.saves.map((save) => save.body)).toEqual([
    {
      models: [
        { model_id: "claude-opus-4-1", price: "stored" },
        { model_id: "claude-sonnet-4-5", price: "stored" },
      ],
    },
  ]);
});

test("every card but OpenRouter's has Models", async ({ page }) => {
  await signIn(page);
  await new PlatformLlmProviderDataSupport(page).intercept({
    connections: [ANTHROPIC_CONNECTION, AZURE_CONNECTION, CUSTOM_CONNECTION],
  });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();

  await expect(settings.modelsButton("Anthropic")).toBeVisible();
  await expect(settings.modelsButton("Azure Europe")).toBeVisible();
  await expect(settings.modelsButton("Aardvark lab")).toBeVisible();
  await expect(settings.modelsButton("OpenRouter")).toHaveCount(0);
});

test("a Custom model takes typed prices, and Save waits until its input and output are above 0", async ({ page }) => {
  await signIn(page);
  const data = new PlatformLlmProviderDataSupport(page);
  await data.intercept({ connections: [CUSTOM_CONNECTION] });
  const mock = await data.interceptModels({ catalogue: CUSTOM_CATALOGUE, models: CUSTOM_MODELS });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();
  await settings.modelsButton("Aardvark lab").click();

  await expect(settings.priceInput("mistral-7b", "Input")).toHaveValue("0.2");
  await expect(settings.priceInput("mistral-7b", "Output")).toHaveValue("0.4");
  await expect(settings.priceInput("mistral-7b", "Cache read")).toHaveValue("0");
  await expect(settings.selectAllPricedButton()).toHaveCount(0);
  await settings.modelCheckbox("llama-3").click();
  await expect(settings.priceInput("llama-3", "Input")).toHaveValue("");
  await expect(settings.saveModelsButton()).toBeDisabled();
  await settings.typePrices("llama-3", ["0", "1", "0", "0"]);
  await expect(settings.saveModelsButton()).toBeDisabled();
  await settings.priceInput("llama-3", "Input").fill("0.5");
  await expect(settings.saveModelsButton()).toBeEnabled();
  await settings.saveModels();

  await expect(settings.toast("Aardvark lab models saved")).toBeVisible();
  expect(mock.saves).toEqual([
    {
      slug: "lab",
      body: {
        models: [
          {
            model_id: "llama-3",
            price: {
              input_cost_per_token: "0.0000005",
              output_cost_per_token: "0.000001",
              cache_read_input_token_cost: "0",
              cache_creation_input_token_cost: "0",
            },
          },
          { model_id: "mistral-7b", price: "stored" },
        ],
      },
    },
  ]);
});

test("a changed typed price is sent in place of the stored one", async ({ page }) => {
  await signIn(page);
  const data = new PlatformLlmProviderDataSupport(page);
  await data.intercept({ connections: [CUSTOM_CONNECTION] });
  const mock = await data.interceptModels({ catalogue: CUSTOM_CATALOGUE, models: CUSTOM_MODELS });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();
  await settings.modelsButton("Aardvark lab").click();

  await settings.priceInput("mistral-7b", "Output").fill("0.45");
  await settings.saveModels();

  await expect(settings.toast("Aardvark lab models saved")).toBeVisible();
  expect(mock.saves.map((save) => save.body)).toEqual([
    {
      models: [
        {
          model_id: "mistral-7b",
          price: {
            input_cost_per_token: "0.0000002",
            output_cost_per_token: "0.00000045",
            cache_read_input_token_cost: "0",
            cache_creation_input_token_cost: "0",
          },
        },
      ],
    },
  ]);
});

async function openAzureDeployments(page: Page) {
  await signIn(page);
  const data = new PlatformLlmProviderDataSupport(page);
  await data.intercept({ connections: [AZURE_CONNECTION] });
  const mock = await data.interceptModels({ catalogue: AZURE_CATALOGUE, models: AZURE_DEPLOYMENTS });
  const settings = new PlatformLlmProvidersPage(page);
  await settings.goto();
  await settings.modelsButton("Azure Europe").click();
  return { mock, settings };
}

test("an Azure deployment is added by name and priced from the model it runs", async ({ page }) => {
  const { mock, settings } = await openAzureDeployments(page);

  await expect(settings.dialog().getByRole("heading", { name: "Azure Europe deployments" })).toBeVisible();
  await expect(settings.runsModelPicker("prod-gpt4o")).toHaveText("gpt-4o");
  await expect(settings.runsModelPicker("lab-router")).toHaveText("Other (type prices)");
  await expect(settings.priceInput("lab-router", "Input")).toHaveValue("1");
  await settings.addDeployment("prod-mini");
  await settings.chooseRunsModel("prod-mini", "mini", "gpt-4o-mini");

  await expect(settings.deploymentCells("prod-mini")).toHaveText([
    "",
    "gpt-4o-mini",
    "$0.15",
    "$0.6",
    "$0.075",
    "$0.15",
    "Remove",
  ]);
  await settings.saveModels();

  await expect(settings.toast("Azure Europe models saved")).toBeVisible();
  expect(mock.saves).toEqual([
    {
      slug: "azure-eu",
      body: {
        models: [
          { model_id: "lab-router", price: "stored" },
          { model_id: "prod-gpt4o", price: "stored" },
          { model_id: "prod-mini", price: "litellm", runs_model: "gpt-4o-mini" },
        ],
      },
    },
  ]);
});

test("an Azure deployment on Other is saved with its typed prices per token", async ({ page }) => {
  const { mock, settings } = await openAzureDeployments(page);

  await settings.addDeployment("router-2");
  await settings.chooseRunsModel("router-2", "other", "Other (type prices)");
  await settings.typePrices("router-2", ["1.5", "6", "0.15", "0"]);
  await settings.saveModels();

  await expect(settings.toast("Azure Europe models saved")).toBeVisible();
  expect(mock.saves.map((save) => save.body.models[2])).toEqual([
    {
      model_id: "router-2",
      price: {
        input_cost_per_token: "0.0000015",
        output_cost_per_token: "0.000006",
        cache_read_input_token_cost: "0.00000015",
        cache_creation_input_token_cost: "0",
      },
    },
  ]);
});

test("an Azure deployment name that breaks the rules or repeats keeps Save disabled", async ({ page }) => {
  const { mock, settings } = await openAzureDeployments(page);

  await settings.addDeployment("bad name!");
  await settings.chooseRunsModel("bad name!", "mini", "gpt-4o-mini");
  await expect(settings.dialog()).toContainText("A deployment name is 1 to 64 letters, digits or . _ - characters.");
  await expect(settings.saveModelsButton()).toBeDisabled();
  await settings.newDeploymentName().fill("prod-gpt4o");
  await expect(settings.dialog()).toContainText("Another deployment has this name.");
  await expect(settings.saveModelsButton()).toBeDisabled();
  await settings.newDeploymentName().fill("prod-gpt4o-2");
  await expect(settings.saveModelsButton()).toBeEnabled();
  expect(mock.saves).toEqual([]);
});

test("a new Azure deployment needs the model it runs before Save", async ({ page }) => {
  const { settings } = await openAzureDeployments(page);

  await settings.addDeployment("prod-mini");

  await expect(settings.runsModelPicker("prod-mini")).toHaveText("Choose a model");
  await expect(settings.saveModelsButton()).toBeDisabled();
});

test("a removed Azure deployment is left out of the save", async ({ page }) => {
  const { mock, settings } = await openAzureDeployments(page);

  await settings.removeDeploymentButton("lab-router").click();
  await settings.saveModels();

  await expect(settings.toast("Azure Europe models saved")).toBeVisible();
  expect(mock.saves.map((save) => save.body)).toEqual([{ models: [{ model_id: "prod-gpt4o", price: "stored" }] }]);
});

test("an Azure deployment whose LiteLLM price changed shows the difference and takes it once accepted", async ({
  page,
}) => {
  const { mock, settings } = await openAzureDeployments(page);

  await expect(settings.deploymentCells("prod-gpt4o")).toHaveText([
    "prod-gpt4oLiteLLM's price has changedUse LiteLLM's price",
    "gpt-4o",
    "$2LiteLLM $2.5",
    "$8LiteLLM $10",
    "$1.25",
    "$2LiteLLM $2.5",
    "Remove",
  ]);
  await settings.useLiteLLMPriceButton("prod-gpt4o").click();
  await expect(settings.deploymentCells("prod-gpt4o")).toHaveText([
    "prod-gpt4oTakes LiteLLM's price when saved",
    "gpt-4o",
    "$2.5",
    "$10",
    "$1.25",
    "$2.5",
    "Remove",
  ]);
  await settings.saveModels();

  await expect(settings.toast("Azure Europe models saved")).toBeVisible();
  expect(mock.saves.map((save) => save.body)).toEqual([
    {
      models: [
        { model_id: "lab-router", price: "stored" },
        { model_id: "prod-gpt4o", price: "litellm", runs_model: "gpt-4o" },
      ],
    },
  ]);
});
