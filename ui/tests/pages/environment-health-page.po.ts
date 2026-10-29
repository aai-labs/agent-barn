import { Locator, Page } from "@playwright/test";

/** Locators and user actions for Platform → Environment Health. Assertions live in the spec. */
export class EnvironmentHealthPage {
  constructor(private page: Page) {}

  async goto() {
    await this.page.goto("/dashboard/platform/environment-health");
  }

  heading(): Locator {
    return this.page.getByRole("heading", { level: 1, name: "Environment Health" });
  }

  level(): Locator {
    return this.page.getByTestId("environment-level");
  }

  sourcesNotice(): Locator {
    return this.page.getByTestId("environment-sources");
  }

  section(name: "capacity" | "services" | "agents" | "workloads" | "volumes" | "events"): Locator {
    return this.page.getByTestId(`environment-${name}`);
  }

  capacityLine(resource: string): Locator {
    return this.page.getByTestId(`capacity-line-${resource}`);
  }

  capacityWarning(): Locator {
    return this.page.getByTestId("environment-capacity-warning");
  }

  service(name: string): Locator {
    return this.page.getByTestId(`service-${name}`);
  }

  failedAgents(): Locator {
    return this.page.getByTestId("failed-agent");
  }

  unhealthyRuntimes(): Locator {
    return this.page.getByTestId("unhealthy-runtime");
  }

  podIssues(): Locator {
    return this.page.getByTestId("pod-issue");
  }

  volumeGroup(group: string): Locator {
    return this.page.getByTestId(`volume-group-${group}`);
  }

  volumeAttention(): Locator {
    return this.page.getByTestId("volume-attention");
  }

  async openQuotaDialog() {
    await this.page.getByTestId("environment-quota-open").click();
  }

  dialog(): Locator {
    return this.page.getByTestId("capacity-limits-dialog");
  }

  /** A quota line's text box, named as `kubectl describe quota` names the line. */
  quotaInput(label: string): Locator {
    return this.dialog().getByLabel(label, { exact: true });
  }

  saveButton(): Locator {
    return this.page.getByTestId("capacity-limits-save");
  }

  refreshButton(): Locator {
    return this.page.getByRole("button", { name: "Refresh" });
  }
}
