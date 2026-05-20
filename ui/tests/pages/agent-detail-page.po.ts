import { Locator, Page } from "@playwright/test";

export class AgentDetailPage {
  constructor(private page: Page) {}

  async goto(agentId = "33333333-3333-4333-8333-333333333333") {
    await this.page.goto(`/dashboard/agents/${agentId}`);
  }

  agentName(name: string): Locator {
    return this.page.getByRole("heading", { name });
  }

  configureButton(): Locator {
    return this.page.getByRole("button", { name: /configure/i });
  }

  configDrawerHeading(): Locator {
    return this.page.getByRole("heading", { name: /configure agent/i });
  }

  configDrawerCloseButton(): Locator {
    return this.page.locator("aside").getByRole("button").first();
  }

  hireButton(): Locator {
    return this.page.getByRole("button", { name: /hire agent/i });
  }
}
