import type { Page } from "@playwright/test";

export class CustomApiPage {
  constructor(private page: Page) {}
  get section() { return this.page.getByRole("region", { name: "Integrations", exact: true }); }
  get form() { return this.section.getByRole("group", { name: "Custom API connection", exact: true }); }
  get add() { return this.section.getByRole("button", { name: "Custom API", exact: true }); }
  get edit() { return this.section.getByRole("button", { name: "Edit", exact: true }); }
  get remove() { return this.section.getByRole("button", { name: "Remove Custom API Inventory API", exact: true }); }
  get save() { return this.section.getByRole("button", { name: /^Apply(?: & Restart)?$/ }); }
  get cancel() { return this.section.getByRole("button", { name: "Cancel", exact: true }); }
  get dialog() { return this.page.getByRole("dialog"); }
  field(name: string) { return this.form.getByLabel(name, { exact: true }); }
  async beginEditing() { await this.edit.click(); }
  async addGithubCredential() {
    await this.section.getByRole("button", { name: /GitHub/ }).click();
    await this.section.getByPlaceholder("github_pat_… or ghp_…").fill("fixture-token");
    await this.section.getByPlaceholder("owner-or-org").fill("fixture-org");
  }
  async expandConnection() { await this.section.locator("summary").filter({ hasText: "Custom API · Inventory API" }).click(); }
  async selectAuth(name: string) {
    await this.field("Authentication").click();
    await this.page.getByRole("option", { name, exact: true }).click();
  }
  async confirmApply() {
    await this.save.click();
    await this.dialog.getByRole("button", { name: /^Apply(?: & Restart)?$/ }).click();
    await this.dialog.waitFor({ state: "hidden" });
  }
}
