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

  agentCard(name: string): Locator {
    return this.page.getByRole("link", { name: `View ${name}`, exact: true });
  }

  hireCard(): Locator {
    return this.page.getByRole("button", { name: "Hire a teammate", exact: true });
  }

  async openHireCard(keyboard = false) {
    if (keyboard) {
      await this.hireCard().focus();
      await this.hireCard().press("Enter");
    } else {
      await this.hireCard().click();
    }
  }

  lastActivityTime(name: string): Locator {
    return this.agentCard(name).locator("time");
  }

  async openAgent(name: string, keyboard = false) {
    const card = this.agentCard(name);
    if (keyboard) {
      await card.focus();
      await card.press("Enter");
    } else {
      await card.click();
    }
  }

  async searchTeammates(value: string) {
    await this.page.getByRole("searchbox", { name: "Search displayed teammates" }).fill(value);
  }

  async cardFooterBottomGap(name: string): Promise<number> {
    return this.agentCard(name).evaluate((card) => {
      const footer = card.lastElementChild!;
      return card.getBoundingClientRect().bottom - footer.getBoundingClientRect().bottom;
    });
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
