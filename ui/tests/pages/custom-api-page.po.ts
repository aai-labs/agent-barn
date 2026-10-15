import type { Page } from "@playwright/test";

export class CustomApiPage {
  constructor(private page: Page) {}

  get section() {
    return this.page.getByRole("region", { name: "Custom API connections" });
  }
  get form() {
    return this.section.getByRole("form", { name: "Custom API connection" });
  }
  get add() {
    return this.section.getByRole("button", { name: "Add Custom API" });
  }
  get edit() {
    return this.section.getByRole("button", { name: "Edit", exact: true });
  }
  get remove() {
    return this.section.getByRole("button", { name: "Delete", exact: true });
  }
  get save() {
    return this.form.getByRole("button", { name: "Save connection" });
  }
  get dialog() {
    return this.page.getByRole("dialog");
  }
  field(name: string) {
    return this.form.getByLabel(name, { exact: true });
  }

  async selectAuth(name: string) {
    await this.field("Authentication").click();
    await this.page.getByRole("option", { name, exact: true }).click();
  }
}
