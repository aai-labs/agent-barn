import type { Locator, Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";

export class RbacUiPage {
  constructor(private page: Page) {}

  async gotoAgent(agentId: string) {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/agents/${agentId}`);
  }

  async gotoSettings() {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/settings`);
  }

  async gotoMembers() {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/members`);
  }

  memberRow(name: string): Locator {
    return this.page.locator(".af-card").filter({ hasText: name });
  }

  async openMemberActions(name: string) {
    await this.memberRow(name).getByRole("button", { name: "Member actions" }).click();
  }

  agentAction(name: RegExp | string): Locator {
    return this.page.getByRole("button", { name });
  }

  /** A section in the navigation panel beside the page. */
  sectionLink(name: string): Locator {
    return this.page.getByRole("complementary").getByRole("link", { name, exact: true });
  }

  agentConfigurationLink(): Locator {
    return this.page.getByRole("complementary").getByRole("link", { name: "Agent settings", exact: true });
  }

  async openSettingsSection(name: "Templates" | "Skills") {
    await this.page.getByRole("complementary").getByRole("link", { name, exact: true }).click();
  }

  newTemplateButton(): Locator {
    return this.page.getByRole("button", { name: /new template/i });
  }

  newSkillButton(): Locator {
    return this.page.getByRole("button", { name: /new skill/i });
  }

  async openTemplate(name: string) {
    await this.page.getByRole("button", { name: new RegExp(name) }).click();
  }

  async closeTemplate() {
    await this.page.getByRole("button", { name: "Templates", exact: true }).first().click();
  }

  async openSkill(name: string) {
    await this.page.getByText(name, { exact: true }).click();
  }
}
