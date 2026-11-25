import { expect, type Page } from "@playwright/test";

export class PlatformLlmProvidersPage {
  constructor(private page: Page) {}

  async goto() {
    await this.page.goto("/dashboard/platform/settings?section=llm-providers");
  }

  providerList() {
    return this.page.getByRole("list", { name: "LLM providers" });
  }

  providersHeading() {
    return this.page.getByRole("heading", { name: /^Providers · \d+ of \d+ connected$/ });
  }

  card() {
    return this.providerCard("OpenRouter");
  }

  deploymentSection() {
    return this.page.getByRole("region", { name: "Set by this deployment", exact: true });
  }

  deploymentCard() {
    return this.deploymentSection().getByRole("region", { name: "OpenRouter", exact: true });
  }

  deploymentKeyButton() {
    return this.deploymentCard().getByRole("button", { name: /^(Replace key|Save a key)$/ });
  }

  toast(text: string) {
    return this.page.locator("[data-sonner-toast]").filter({ hasText: text });
  }

  openDialogButton() {
    return this.card().getByRole("button", { name: /^(Replace key|Save a key)$/ });
  }

  dialog() {
    return this.page.getByRole("dialog");
  }

  keyInput(provider = "OpenRouter") {
    return this.dialog().getByLabel(`${provider} API key`, { exact: true });
  }

  async submitKey(key: string) {
    await this.openDialogButton().click();
    await this.keyInput().fill(key);
    await this.dialog().getByRole("button", { name: "Save key" }).click();
  }

  async cancelDialog() {
    await this.dialog().getByRole("button", { name: "Cancel" }).click();
  }

  providerCard(name: string) {
    return this.providerList().getByRole("region", { name, exact: true });
  }

  providerCardNames() {
    return this.providerList().getByRole("heading", { level: 3 });
  }

  cardButtons(name: string) {
    return this.providerCard(name).getByRole("button");
  }

  manageButton(name: string) {
    return this.providerCard(name).getByRole("button", { name: `Manage ${name}`, exact: true });
  }

  manageMenu() {
    return this.page.getByRole("menu");
  }

  manageActions() {
    return this.manageMenu().getByRole("menuitem");
  }

  manageAction(action: "Models" | "Organizations" | "Replace key" | "Save a key" | "Delete") {
    return this.manageMenu().getByRole("menuitem", { name: action, exact: true });
  }

  async manage(name: string, action: "Models" | "Organizations" | "Replace key" | "Delete") {
    await this.manageButton(name).click();
    await this.manageAction(action).click();
    await expect(this.manageMenu()).toHaveCount(0);
  }

  async openReplaceKey(name: string) {
    await this.manage(name, "Replace key");
  }

  async openDelete(name: string) {
    await this.manage(name, "Delete");
  }

  async openModels(name: string) {
    await this.manage(name, "Models");
  }

  async openOrganizations(name: string) {
    await this.manage(name, "Organizations");
  }

  accessOption(label: string) {
    return this.dialog().getByRole("radio", { name: label, exact: true });
  }

  organizationSearch() {
    return this.dialog().getByLabel("Search organizations", { exact: true });
  }

  organizationCheckbox(name: string) {
    return this.dialog().getByRole("checkbox", { name, exact: true });
  }

  organizationCheckboxes() {
    return this.dialog().getByRole("checkbox");
  }

  showMoreOrganizations() {
    return this.dialog().getByRole("button", { name: "Show more", exact: true });
  }

  tickedOrganizations() {
    return this.dialog().getByText(/^\d+ ticked$/);
  }

  saveOrganizationsButton() {
    return this.dialog().getByRole("button", { name: "Save organizations" });
  }

  addProviderButton() {
    return this.page.getByRole("button", { name: "Add provider" });
  }

  addKeyButton(name: string) {
    return this.providerCard(name).getByRole("button", { name: /^(Add key|Add endpoint)$/ });
  }

  providerSelect() {
    return this.dialog().getByRole("combobox", { name: "Provider" });
  }

  nameInput() {
    return this.dialog().getByLabel("Name", { exact: true });
  }

  slugInput() {
    return this.dialog().getByLabel("Slug", { exact: true });
  }

  baseUrlInput() {
    return this.dialog().getByLabel("Base URL", { exact: true });
  }

  apiKeyInput() {
    return this.dialog().getByLabel("API key", { exact: true });
  }

  async addProvider(input: { provider: string; key: string; name?: string; slug?: string; baseUrl?: string }) {
    await this.addKeyButton(input.provider).click();
    if (input.name !== undefined) await this.nameInput().fill(input.name);
    if (input.slug !== undefined) await this.slugInput().fill(input.slug);
    if (input.baseUrl !== undefined) await this.baseUrlInput().fill(input.baseUrl);
    await this.apiKeyInput().fill(input.key);
    await this.dialog().getByRole("button", { name: "Add provider" }).click();
  }

  async replaceKey(name: string, input: { key: string; baseUrl?: string }) {
    await this.openReplaceKey(name);
    if (input.baseUrl !== undefined) await this.baseUrlInput().fill(input.baseUrl);
    await this.keyInput(name).fill(input.key);
    await this.dialog().getByRole("button", { name: "Save key" }).click();
  }

  async confirmDelete() {
    await this.dialog().getByRole("button", { name: "Delete provider" }).click();
  }

  modelCheckbox(modelId: string) {
    return this.dialog().getByRole("checkbox", { name: modelId, exact: true });
  }

  modelCheckboxes() {
    return this.dialog().getByRole("checkbox");
  }

  modelCells(modelId: string) {
    return this.dialog()
      .getByRole("row")
      .filter({ has: this.page.getByRole("checkbox", { name: modelId, exact: true }) })
      .getByRole("cell");
  }

  modelFilter() {
    return this.dialog().getByLabel("Filter models", { exact: true });
  }

  selectAllPricedButton() {
    return this.dialog().getByRole("button", { name: "Select all priced", exact: true });
  }

  tickedCount() {
    return this.dialog().getByText(/^\d+ of 50 ticked$/);
  }

  modelsNoLongerListed() {
    return this.dialog().getByRole("region", { name: "Models no longer listed" });
  }

  saveModelsButton() {
    return this.dialog().getByRole("button", { name: "Save models" });
  }

  async saveModels() {
    await this.saveModelsButton().click();
  }

  priceInput(modelId: string, column: "Input" | "Output" | "Cache read" | "Cache write") {
    return this.dialog().getByLabel(`${modelId} ${column} price per 1M tokens`, { exact: true });
  }

  async typePrices(modelId: string, prices: [string, string, string, string]) {
    const columns = ["Input", "Output", "Cache read", "Cache write"] as const;
    for (const [index, column] of columns.entries()) await this.priceInput(modelId, column).fill(prices[index]);
  }

  useLiteLLMPriceButton(modelId: string) {
    return this.dialog().getByRole("button", { name: `Use LiteLLM's price for ${modelId}`, exact: true });
  }

  runsModelPicker(deployment: string) {
    return this.dialog().getByRole("combobox", { name: `Model ${deployment} runs`, exact: true });
  }

  deploymentCells(deployment: string) {
    return this.dialog()
      .getByRole("row")
      .filter({ has: this.page.getByRole("combobox", { name: `Model ${deployment} runs`, exact: true }) })
      .getByRole("cell");
  }

  newDeploymentName() {
    return this.dialog().getByLabel(/^New deployment \d+ name$/).last();
  }

  async addDeployment(name: string) {
    await this.dialog().getByRole("button", { name: "Add deployment" }).click();
    await this.newDeploymentName().fill(name);
  }

  async chooseRunsModel(deployment: string, search: string, option: string) {
    await this.runsModelPicker(deployment).click();
    const searchInput = this.page.getByPlaceholder("Search LiteLLM's Azure models…");
    await searchInput.fill(search);
    await this.page.getByRole("option", { name: option, exact: true }).click();
    await expect(searchInput).toBeHidden();
  }

  removeDeploymentButton(deployment: string) {
    return this.dialog().getByRole("button", { name: `Remove ${deployment}`, exact: true });
  }
}
