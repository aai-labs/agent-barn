import type { Locator, Page } from "@playwright/test";

/** Locators and user actions for Platform → Settings → Agent sizes. Assertions live in the spec. */
export class AgentSizesSettingsPage {
  constructor(private page: Page) {}

  async goto() {
    await this.page.goto("/dashboard/platform/settings?section=agent-sizes");
  }

  heading(): Locator {
    return this.page.getByRole("heading", { name: "Agent sizes", level: 1 });
  }

  row(name: string): Locator {
    return this.page.getByTestId(`agent-size-row-${name}`);
  }

  rows(): Locator {
    return this.page.getByRole("table", { name: "Agent sizes" }).locator("tbody tr");
  }

  enabledSwitch(name: string): Locator {
    return this.page.getByRole("switch", { name: `${name} enabled`, exact: true });
  }

  async openActions(name: string) {
    await this.page.getByRole("button", { name: `${name} actions`, exact: true }).click();
  }

  action(name: "Edit" | "Make default" | "Delete"): Locator {
    return this.page.getByRole("menuitem", { name, exact: true });
  }

  async addSize() {
    await this.page.getByRole("button", { name: "Add size" }).click();
  }

  dialog(): Locator {
    return this.page.getByTestId("agent-size-dialog");
  }

  field(label: string): Locator {
    return this.dialog().getByLabel(label, { exact: true });
  }

  async fill(values: Partial<Record<"Name" | "CPU request (vCPU)" | "CPU limit (vCPU)" | "Memory request (MiB)" | "Memory limit (MiB)", string>>) {
    for (const [label, value] of Object.entries(values)) {
      await this.field(label).fill(value);
    }
  }

  async submit() {
    await this.dialog().locator('button[type="submit"]').click();
  }

  confirmDialog(): Locator {
    return this.page.getByRole("dialog");
  }

  confirm(name: "Make default" | "Disable size"): Locator {
    return this.confirmDialog().getByRole("button", { name, exact: true });
  }

  confirmDelete(): Locator {
    return this.page.getByRole("button", { name: "Delete size" });
  }
}
