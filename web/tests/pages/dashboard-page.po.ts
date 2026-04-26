import { Locator, Page } from "@playwright/test";

export class DashboardPage {
  constructor(private page: Page) {}

  async goto() {
    await this.page.goto("/dashboard");
  }

  heading(): Locator {
    return this.page.getByRole("heading", { name: "Dashboard" });
  }

  async gotoUsers() {
    await this.page.goto("/dashboard/users");
  }

  async gotoOrganizations() {
    await this.page.goto("/dashboard/organizations");
  }

  searchInput(name: string | RegExp): Locator {
    return this.page.getByRole("textbox", { name });
  }
}
