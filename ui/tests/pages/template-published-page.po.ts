import type { Page } from "@playwright/test";

export class TemplatePublishedPage {
  constructor(private page: Page) {}

  get soulContent() {
    return this.page.getByLabel("SOUL.md content");
  }

  get editableSoulContent() {
    return this.page.getByRole("textbox", { name: "SOUL.md content", exact: true });
  }

  async selectVersion(label: string) {
    await this.page.getByRole("combobox", { name: "Published version" }).click();
    await this.page.getByRole("option", { name: label, exact: true }).click();
  }

  get versionOptions() {
    return this.page.getByRole("option");
  }

  async openVersionPicker() {
    await this.page.getByRole("combobox", { name: "Published version" }).click();
  }

  async closeVersionPicker() {
    await this.page.keyboard.press("Escape");
  }

  async selectLastVersionWithKeyboard() {
    const picker = this.page.getByRole("combobox", { name: "Published version" });
    await picker.focus();
    await picker.press("ArrowDown");
    await this.page.getByRole("option", { selected: true }).press("End");
    await this.versionOptions.last().press("Enter");
  }

  async restoreBuiltIn(version: number) {
    await this.page.getByRole("button", { name: `Restore Built-in v${version} as draft`, exact: true }).click();
  }
}
