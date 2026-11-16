import { Locator, Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { MOCK_AGENT_ID } from "./data-support/agent-data-support.po";

/** Locators and user actions for the Agent Anomalies tab and the Unusual activity setting. */
export class AgentAnomaliesPage {
  constructor(private page: Page) {}

  async goto(agentId = MOCK_AGENT_ID, orgId = TEST_ORG_ID) {
    await this.page.goto(`/dashboard/${orgId}/agents/${agentId}?tab=anomalies`);
  }

  async gotoSettings(orgId = TEST_ORG_ID) {
    await this.page.goto(`/dashboard/${orgId}/settings?tab=unusual-activity`);
  }

  /** The Anomalies section in the navigation panel. */
  tab(): Locator {
    return this.page.getByRole("complementary").getByRole("link", { name: "Anomalies", exact: true });
  }

  anomalies(): Locator {
    return this.page.getByTestId("anomaly");
  }

  anomalyList(): Locator {
    return this.page.getByRole("region", { name: "Flagged activity" });
  }

  normal(): Locator {
    return this.page.getByRole("region", { name: "Normal behaviour" });
  }

  detectionSetting(): Locator {
    return this.page.getByRole("region", { name: "Unusual activity checks" });
  }

  async edit(section: Locator) {
    await section.getByRole("button", { name: "Edit", exact: true }).click();
  }

  async chooseSensitivity(option: string) {
    await this.normal().getByRole("combobox", { name: "Sensitivity" }).click();
    await this.page.getByRole("option", { name: option }).click();
  }

  async apply(label: string, confirmLabel: string) {
    await this.page.getByRole("button", { name: label, exact: true }).click();
    await this.page.getByRole("dialog").getByRole("button", { name: confirmLabel, exact: true }).click();
  }
}
