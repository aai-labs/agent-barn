import { Page } from "@playwright/test";

export class PlatformMemorySettingsPage {
  constructor(private page: Page) {}
  async goto() {
    await this.page.goto("/dashboard/platform/settings");
  }
  model() {
    return this.page.getByRole("combobox", { name: "Memory processing model" });
  }
  save() {
    return this.page.getByRole("button", { name: "Save", exact: true });
  }
  async edit() {
    await this.page.getByRole("button", { name: "Edit", exact: true }).click();
  }
  summary() {
    return this.page.getByTestId("saved-memory-model");
  }
  async choose(name: string) {
    await this.model()
      .or(this.page.getByRole("button", { name: "Edit", exact: true }))
      .waitFor({ state: "visible" });
    if (
      await this.page
        .getByRole("button", { name: "Edit", exact: true })
        .isVisible()
    )
      await this.edit();
    await this.model().click();
    await this.page.getByPlaceholder("Search memory models…").fill(name);
    await this.page.getByRole("option", { name }).click();
  }
}
