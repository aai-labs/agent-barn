import { Locator, Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { MOCK_AGENT_ID } from "./data-support/agent-data-support.po";

/** Locators and user actions for the Agent Playbooks tab and the Platform Playbooks setting. */
export class AgentPlaybooksPage {
  constructor(private page: Page) {}

  async goto(agentId = MOCK_AGENT_ID, orgId = TEST_ORG_ID) {
    await this.page.goto(`/dashboard/${orgId}/agents/${agentId}?tab=playbooks`);
  }

  async gotoPlatformSettings() {
    await this.page.goto("/dashboard/platform/settings?section=playbooks");
  }

  tab(): Locator {
    return this.page.getByRole("button", { name: "Playbooks", exact: true });
  }

  form(): Locator {
    return this.page.getByRole("region", { name: "Create a playbook" });
  }

  preview(): Locator {
    return this.page.getByTestId("playbook-preview");
  }

  createButton(): Locator {
    return this.page.getByRole("button", { name: "Create playbook" });
  }

  runs(): Locator {
    return this.page.getByTestId("playbook-run");
  }

  async writeToExistingPlaybook() {
    await this.page.getByRole("radio", { name: "The next draft of a playbook" }).click();
  }

  async choose(label: string, option: string) {
    await this.form().getByRole("combobox", { name: label }).click();
    await this.page.getByRole("option", { name: option }).click();
  }

  async create() {
    await this.createButton().click();
  }

  async cancelRun(run: Locator) {
    await run.getByRole("button", { name: "Cancel" }).click();
    await this.page.getByRole("button", { name: "Cancel run" }).click();
  }

  platformModelSummary(): Locator {
    return this.page.getByTestId("saved-playbook-model");
  }

  async choosePlatformModel(name: string) {
    await this.page.getByRole("button", { name: "Edit", exact: true }).click();
    await this.page.getByRole("combobox", { name: "Playbook extraction model" }).click();
    await this.page.getByPlaceholder("Search playbook models…").fill(name);
    await this.page.getByRole("option", { name }).click();
    await this.page.getByRole("button", { name: "Save", exact: true }).click();
  }
}
