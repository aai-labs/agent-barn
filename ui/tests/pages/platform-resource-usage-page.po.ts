import { Locator, Page } from "@playwright/test";

export class PlatformResourceUsagePage {
  constructor(private page: Page) {}

  async goto(query = "") {
    await this.page.goto(`/dashboard/platform/resource-usage${query}`);
  }

  heading(): Locator {
    return this.page.getByRole("heading", { level: 1, name: "Platform Resource Usage" });
  }

  stat(name: "memory" | "cpu" | "reporting" | "near-limit" | "throttled"): Locator {
    return this.page.getByTestId(`platform-usage-${name}`);
  }

  organizationRows(): Locator {
    return this.page.getByTestId("organization-usage-row");
  }

  organizationRow(id: string): Locator {
    return this.page.locator(`[data-testid="organization-usage-row"][data-organization-id="${id}"]`);
  }

  agentRows(): Locator {
    return this.page.getByTestId("platform-agent-usage-row");
  }

  /** The names in the order the table draws them. */
  async agentIds(): Promise<(string | null)[]> {
    return this.agentRows().evaluateAll((rows) => rows.map((row) => row.getAttribute("data-agent-id")));
  }

  async chooseRange(label: string) {
    await this.page.getByTestId("platform-usage-range").click();
    await this.page.getByRole("option", { name: label }).click();
  }

  navLink(name: string): Locator {
    return this.page.locator("header nav").getByRole("link", { name, exact: true });
  }

  capacityCard(kind: "memory" | "cpu"): Locator {
    return this.page.getByTestId(`capacity-${kind}`);
  }

  capacityWarning(): Locator {
    return this.page.getByTestId("capacity-warning");
  }

  async openCapacityDialog() {
    await this.page.getByTestId("capacity-limits-open").click();
  }

  dialog(): Locator {
    return this.page.getByTestId("capacity-limits-dialog");
  }

  memoryInput(): Locator {
    return this.page.getByLabel("Memory (GiB)");
  }

  cpuInput(): Locator {
    return this.page.getByLabel("CPU (cores)");
  }

  saveButton(): Locator {
    return this.page.getByTestId("capacity-limits-save");
  }

  /** The chevron of an Agent's row. Absent for a container with no live agent. */
  agentToggle(agentId: string): Locator {
    return this.page.locator(
      `[data-testid="platform-agent-usage-row"][data-agent-id="${agentId}"] button[aria-expanded]`,
    );
  }

  agentDetails(): Locator {
    return this.page.getByTestId("platform-agent-details");
  }
}
