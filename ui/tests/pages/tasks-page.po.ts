import { Locator, Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { MOCK_AGENT_ID } from "./data-support/agent-data-support.po";

/** Locators and user actions for an Agent's Tasks tab and the Organization's Tasks page. */
export class TasksPage {
  constructor(private page: Page) {}

  async gotoAgentTab(agentId = MOCK_AGENT_ID, orgId = TEST_ORG_ID) {
    await this.page.goto(`/dashboard/${orgId}/agents/${agentId}?tab=tasks`);
  }

  async gotoOrganization(orgId = TEST_ORG_ID) {
    await this.page.goto(`/dashboard/${orgId}/tasks`);
  }

  /** The Tasks section in the Agent's navigation panel. */
  agentTab(): Locator {
    return this.page.getByRole("complementary").getByRole("link", { name: "Tasks", exact: true });
  }

  /** The Tasks entry in the Organization's rail. */
  railEntry(): Locator {
    return this.page.getByRole("navigation").getByRole("link", { name: "Tasks", exact: true }).first();
  }

  rows(): Locator {
    return this.page.getByTestId("task-row");
  }

  detail(): Locator {
    return this.page.getByRole("dialog");
  }

  async open(title: string) {
    await this.rows().filter({ hasText: title }).getByRole("button").first().click();
  }

  async filterBy(label: string, option: string) {
    await this.page.getByRole("combobox", { name: label }).click();
    await this.page.getByRole("option", { name: option, exact: true }).click();
  }
}
