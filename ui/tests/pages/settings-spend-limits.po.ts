import { Page, expect } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";

/** Locators and user actions for Settings → Spend limits. Assertions live in the spec. */
export class SettingsSpendLimitsPage {
  constructor(private page: Page) {}

  get heading() {
    return this.page.getByRole("heading", { name: "Spend limits", exact: true });
  }

  get organizationLimit() {
    return this.page.getByRole("region", { name: "Organization limit" });
  }

  get defaultAgentLimit() {
    return this.page.getByRole("region", { name: "Default Agent limit" });
  }

  get agentLimits() {
    return this.page.getByRole("table");
  }

  get dialog() {
    return this.page.getByRole("dialog");
  }

  async open() {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/settings?tab=spend-limits`);
    await expect(this.heading).toBeVisible();
  }

  async editOrganizationLimit() {
    await this.organizationLimit.getByRole("button", { name: "Edit" }).click();
  }

  async setLowerOrganizationLimit(amount: string) {
    await this.page.getByLabel("Your limit (US dollars)", { exact: true }).fill(amount);
  }

  /** Empty means "follow the maximum"; this is the explicit way back to it. */
  async useMaximum() {
    await this.organizationLimit.getByRole("button", { name: "Use the maximum" }).click();
  }

  async editDefaultAgentLimit() {
    await this.defaultAgentLimit.getByRole("button", { name: "Edit" }).click();
  }

  async enterDefaultAgentLimit(amount: string) {
    await this.page.getByLabel("Default limit (US dollars)", { exact: true }).fill(amount);
  }

  /** Opens a card's confirmation dialog. */
  async apply(section: "organization" | "default", label: string) {
    const region = section === "organization" ? this.organizationLimit : this.defaultAgentLimit;
    await region.getByRole("button", { name: label }).click();
  }

  /** Confirms it, which is what actually saves. */
  async confirm(label: string) {
    await this.dialog.getByRole("button", { name: label }).click();
  }
}
