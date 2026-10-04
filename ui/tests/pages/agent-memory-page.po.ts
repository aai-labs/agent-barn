import { Locator, Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { MOCK_AGENT_ID } from "./data-support/agent-data-support.po";

/** Locators and user actions for the Agent Memory UI. Assertions live in the spec. */
export class AgentMemoryPage {
  constructor(private page: Page) {}

  async gotoMemorySettings(agentId = MOCK_AGENT_ID, orgId = TEST_ORG_ID) {
    await this.page.goto(`/dashboard/${orgId}/agents/${agentId}/configuration?section=memory`);
  }

  async gotoMemoryTab(agentId = MOCK_AGENT_ID, orgId = TEST_ORG_ID, tab = "memory") {
    await this.page.goto(`/dashboard/${orgId}/agents/${agentId}?tab=${tab}`);
  }

  async gotoMemoryAccess(orgId = TEST_ORG_ID, tab = "memory-access") {
    await this.page.goto(`/dashboard/${orgId}/settings?tab=${tab}`);
  }

  async gotoOrganizationMemory(orgId = TEST_ORG_ID) {
    await this.page.goto(`/dashboard/${orgId}/settings?tab=organization-memory`);
  }

  // --- Agent memory setting ---

  settingsSection(): Locator {
    return this.page.getByRole("region", { name: "Long-term memory" });
  }

  async editSetting() {
    await this.settingsSection().getByRole("button", { name: "Edit" }).click();
  }

  async toggleSetting() {
    await this.settingsSection().getByRole("checkbox").click();
  }

  async saveSetting(label = "Save") {
    await this.settingsSection().getByRole("button", { name: label, exact: true }).click();
    await this.page.getByRole("dialog").getByRole("button", { name: label, exact: true }).click();
  }

  // --- Memory access (grants) ---

  grantsSection(): Locator {
    return this.page.getByRole("region", { name: "Current memory access" });
  }

  grantForm(): Locator {
    return this.page.getByRole("region", { name: "Grant memory access" });
  }

  async chooseReader(name: string) {
    await this.page.getByRole("combobox", { name: "Agent receiving access" }).click();
    await this.page.getByRole("option", { name, exact: true }).click();
  }

  async chooseSource(name: string) {
    await this.page.getByRole("combobox", { name: "Memory to access" }).click();
    await this.page.getByRole("option", { name, exact: true }).click();
  }

  async chooseOrganizationPermission(name: string) {
    await this.page.getByRole("combobox", { name: "Organization Memory permission" }).click();
    await this.page.getByRole("option", { name, exact: true }).click();
  }

  sourceOptions(): Locator {
    return this.page.getByRole("listbox").getByRole("option");
  }

  async openSourceChoices() {
    await this.page.getByRole("combobox", { name: "Memory to access" }).click();
  }

  grantButton(): Locator {
    return this.page.getByRole("button", { name: /Grant (read|read and write) access/ });
  }

  async revoke(grantText: string) {
    await this.grantsSection().getByRole("button", { name: `Revoke ${grantText}` }).click();
    await this.page.getByRole("dialog").getByRole("button", { name: "Revoke access" }).click();
  }

  // --- Memory viewer ---

  tab(): Locator {
    return this.page.getByRole("button", { name: "Memory", exact: true });
  }

  viewer(): Locator {
    return this.page.getByRole("region", { name: "Saved memories" });
  }

  async search(text: string) {
    await this.viewer().getByRole("searchbox", { name: "Search saved memories" }).fill(text);
    await this.viewer().getByRole("button", { name: "Search", exact: true }).click();
  }

  async nextPage() {
    await this.viewer().getByRole("button", { name: "Next" }).click();
  }
}
