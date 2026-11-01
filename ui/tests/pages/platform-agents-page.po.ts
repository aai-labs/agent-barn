import type { Locator, Page } from "@playwright/test";

/** Locators and user actions for Platform → Agents. Assertions live in the spec. */
export class PlatformAgentsPage {
  constructor(private page: Page) {}

  async goto() {
    await this.page.goto("/dashboard/platform/agents");
  }

  heading(): Locator {
    return this.page.getByRole("heading", { name: "Agents", level: 1 });
  }

  /** One Organization's group, named by the Organization. */
  organization(name: string): Locator {
    return this.page.getByRole("region", { name, exact: true });
  }

  row(agentId: string): Locator {
    return this.page.getByTestId(`platform-agent-row-${agentId}`);
  }

  async search(text: string) {
    await this.page.getByPlaceholder("Search by agent or organization").fill(text);
  }

  async openOverride(agentName: string) {
    await this.page.getByRole("button", { name: `Override spec of ${agentName}`, exact: true }).click();
  }

  dialog(): Locator {
    return this.page.getByTestId("override-agent-size-dialog");
  }

  async chooseSize(label: string) {
    await this.dialog().getByRole("combobox", { name: "Spec" }).click();
    await this.page.getByRole("option", { name: label }).click();
  }

  async setSize() {
    await this.dialog().getByRole("button", { name: "Set spec" }).click();
  }

  async clearOverride() {
    await this.dialog().getByRole("button", { name: "Clear override" }).click();
  }
}
