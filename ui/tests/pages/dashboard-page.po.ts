import { TEST_ORG_ID } from "../constants";
import { Locator, Page } from "@playwright/test";

export class DashboardPage {
  constructor(private page: Page) {}

  async goto() {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}`);
  }

  nameSuggestionError(): Locator {
    return this.page.getByRole("alert").filter({ hasText: "Could not suggest a name" });
  }

  async retryNameSuggestion() {
    await this.page.getByRole("button", { name: "Retry name suggestion" }).click();
  }

  async closeHireDialog() {
    await this.page.getByRole("button", { name: "Close hiring dialog" }).click();
  }

  agentNameInput(): Locator {
    return this.page.getByRole("textbox", { name: "Agent name", exact: true });
  }

  async chooseHireTemplate(name: string) {
    await this.page.getByRole("combobox").nth(1).click();
    await this.page.getByRole("option", { name, exact: true }).click();
  }

  async submitHire() {
    await this.page.getByRole("button", { name: "Hire Agent", exact: true }).click();
  }

  heading(): Locator {
    return this.page.getByRole("heading", { name: "Your team" });
  }

  async gotoUsers() {
    await this.page.goto("/dashboard/platform/users");
  }

  async gotoOrganizations() {
    await this.page.goto("/dashboard/platform/organizations");
  }

  searchInput(name: string | RegExp): Locator {
    return this.page.getByRole("textbox", { name });
  }
}
