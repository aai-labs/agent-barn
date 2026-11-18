import { Locator, Page } from "@playwright/test";

/** Locators and user actions for the Platform Decisions setting. */
export class PlatformDecisionSettingsPage {
  constructor(private page: Page) {}

  async goto() {
    await this.page.goto("/dashboard/platform/settings?section=decisions");
  }

  /** The Decisions section in the navigation panel. */
  tab(): Locator {
    return this.page.getByRole("complementary").getByRole("link", { name: "Decisions", exact: true });
  }

  modelSummary(): Locator {
    return this.page.getByTestId("saved-decision-model");
  }

  async chooseModel(name: string) {
    await this.page.getByRole("button", { name: "Edit", exact: true }).click();
    await this.page.getByRole("combobox", { name: "Decision model" }).click();
    await this.page.getByPlaceholder("Search decision models…").fill(name);
    await this.page.getByRole("option", { name }).click();
    await this.page.getByRole("button", { name: "Save", exact: true }).click();
  }
}
