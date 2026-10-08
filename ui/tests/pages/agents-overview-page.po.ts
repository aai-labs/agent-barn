import { Locator, Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";

export class AgentsOverviewPage {
  constructor(private page: Page) {}

  async goto(query = "") {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/agents${query}`);
  }

  heading(): Locator {
    return this.page.getByRole("heading", { level: 1, name: "Usage" });
  }

  rows(): Locator {
    return this.page.getByTestId("agents-overview-row");
  }

  row(name: string): Locator {
    return this.page.locator(`[data-testid="agents-overview-row"][data-agent-name="${name}"]`);
  }

  /** The names in the order the table draws them. */
  async names(): Promise<(string | null)[]> {
    return this.rows().evaluateAll((rows) => rows.map((row) => row.getAttribute("data-agent-name")));
  }

  sortButton(key: "name" | "spend" | "cpu" | "memory"): Locator {
    return this.page.getByTestId(`agents-overview-sort-${key}`);
  }

  /** Found through its row, not its label: the label flips from "Show" to "Hide" as it opens. */
  toggleFor(name: string): Locator {
    return this.row(name).locator("button[aria-expanded]");
  }

  details(): Locator {
    return this.page.getByTestId("agent-overview-details");
  }

  async choosePeriod(label: string) {
    await this.page.getByTestId("agents-overview-period").click();
    await this.page.getByRole("option", { name: label }).click();
  }

  navLink(name: string): Locator {
    return this.page.locator("header nav").getByRole("link", { name, exact: true });
  }
}
