import { Page, expect } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";

/** Locators and user actions for Settings → Agents. Assertions live in the spec. */
export class SettingsAgentDefaultsPage {
  constructor(private page: Page) {}

  get heading() {
    return this.page.getByRole("heading", { name: "Agents" });
  }

  get defaultModelSection() {
    return this.page.getByRole("region", { name: "Default model" });
  }

  async open() {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/settings`);
    await expect(this.heading).toBeVisible();
  }

  async editDefaultModel() {
    await this.defaultModelSection.getByRole("button", { name: "Edit" }).click();
  }

  async chooseModel(name: RegExp) {
    await this.page.getByRole("button", { name: "Default model" }).click();
    await this.page.getByRole("option", { name }).click();
  }

  /** Opens the confirmation dialog. */
  async apply(label: string) {
    await this.defaultModelSection.getByRole("button", { name: label }).click();
  }

  /** Confirms it, which is what actually saves. */
  async confirm(label: string) {
    await this.page.getByRole("dialog").getByRole("button", { name: label }).click();
  }
}
