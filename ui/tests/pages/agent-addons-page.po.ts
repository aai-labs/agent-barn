import type { Locator, Page } from "@playwright/test";

/** Locators and user actions for an Agent's Add-ons section. Assertions live in the spec. */
export class AgentAddonsSection {
  constructor(private page: Page) {}

  async goto(agentId: string, orgId: string) {
    await this.page.goto(`/dashboard/${orgId}/agents/${agentId}/configuration?section=addons`);
  }

  section(): Locator {
    return this.page.getByTestId("agent-addons-settings");
  }

  addon(name: string): Locator {
    return this.section().getByRole("listitem", { name, exact: true });
  }

  pendingNote(): Locator {
    return this.page.getByTestId("agent-pending-addons-note");
  }

  requestButton(): Locator {
    return this.section().getByRole("button", { name: "Request add-on" });
  }

  dialog(): Locator {
    return this.page.getByTestId("request-addon-dialog");
  }

  async chooseKind(label: string) {
    await this.dialog().getByRole("combobox", { name: "Kind" }).click();
    await this.page.getByRole("option", { name: label, exact: true }).click();
  }

  async fill(label: string, value: string) {
    await this.dialog().getByLabel(label, { exact: true }).fill(value);
  }

  async submitRequest() {
    await this.dialog().getByRole("button", { name: "Request add-on" }).click();
  }

  async withdraw(name: string) {
    await this.addon(name).getByRole("button", { name: "Withdraw" }).click();
    await this.page.getByRole("dialog").getByRole("button", { name: "Withdraw" }).click();
  }
}

/** Locators and user actions for Platform → Add-ons. Assertions live in the spec. */
export class PlatformAgentAddonsPage {
  constructor(private page: Page) {}

  async goto(query = "") {
    await this.page.goto(`/dashboard/platform/agent-addons${query}`);
  }

  heading(): Locator {
    return this.page.getByRole("heading", { name: "Add-ons", level: 1 });
  }

  request(name: string): Locator {
    return this.page.getByRole("listitem", { name, exact: true });
  }

  async filterState(label: string) {
    await this.page.getByRole("combobox", { name: "State" }).click();
    await this.page.getByRole("option", { name: label, exact: true }).click();
  }

  async decide(name: string, action: "Approve" | "Reject" | "Revoke") {
    await this.request(name).getByRole("button", { name: action, exact: true }).click();
  }

  confirmation(): Locator {
    return this.page.getByRole("dialog");
  }

  async confirm(action: "Approve" | "Reject" | "Revoke") {
    await this.confirmation().getByRole("button", { name: action, exact: true }).click();
  }
}
