import { TEST_ORG_ID } from "../constants";
import { Locator, Page } from "@playwright/test";

export class DashboardPage {
  constructor(private page: Page) {}

  async goto() {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}`);
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
