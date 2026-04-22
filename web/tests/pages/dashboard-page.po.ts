import { Locator, Page } from "@playwright/test";

export class DashboardPage {
  constructor(private page: Page) {}

  async goto() {
    await this.page.goto("/dashboard");
  }

  heading(): Locator {
    return this.page.getByRole("heading", { name: "Dashboard" });
  }
}
