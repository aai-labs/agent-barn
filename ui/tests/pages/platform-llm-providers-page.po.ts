import type { Page } from "@playwright/test";

export class PlatformLlmProvidersPage {
  constructor(private page: Page) {}

  async goto() {
    await this.page.goto("/dashboard/platform/settings?section=llm-providers");
  }

  card() {
    return this.page.getByRole("region", { name: "OpenRouter" });
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

  otherProviders() {
    return this.page.getByRole("region", { name: "Other providers" });
  }

  providerCard(name: string) {
    return this.otherProviders().getByRole("region", { name, exact: true });
  }

  providerCardNames() {
    return this.otherProviders().getByRole("heading", { level: 4 });
  }

  replaceKeyButton(name: string) {
    return this.providerCard(name).getByRole("button", { name: "Replace key" });
  }

  deleteButton(name: string) {
    return this.providerCard(name).getByRole("button", { name: "Delete" });
  }

  addProviderButton() {
    return this.otherProviders().getByRole("button", { name: "Add provider" });
  }

  providerSelect() {
    return this.dialog().getByRole("combobox", { name: "Provider" });
  }

  providerOptions() {
    return this.page.getByRole("option");
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

  async chooseProvider(label: string) {
    await this.providerSelect().click();
    await this.page.getByRole("option", { name: label, exact: true }).click();
  }

  async addProvider(input: { provider?: string; key: string; name?: string; slug?: string; baseUrl?: string }) {
    await this.addProviderButton().click();
    if (input.provider) await this.chooseProvider(input.provider);
    if (input.name !== undefined) await this.nameInput().fill(input.name);
    if (input.slug !== undefined) await this.slugInput().fill(input.slug);
    if (input.baseUrl !== undefined) await this.baseUrlInput().fill(input.baseUrl);
    await this.apiKeyInput().fill(input.key);
    await this.dialog().getByRole("button", { name: "Add provider" }).click();
  }

  async replaceKey(name: string, input: { key: string; baseUrl?: string }) {
    await this.replaceKeyButton(name).click();
    if (input.baseUrl !== undefined) await this.baseUrlInput().fill(input.baseUrl);
    await this.keyInput(name).fill(input.key);
    await this.dialog().getByRole("button", { name: "Save key" }).click();
  }

  async confirmDelete() {
    await this.dialog().getByRole("button", { name: "Delete provider" }).click();
  }
}
