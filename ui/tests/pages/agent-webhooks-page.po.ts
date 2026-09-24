import { Locator, Page } from "@playwright/test";

export class AgentWebhooksPage {
  constructor(private page: Page) {}

  async goto(agentId: string, orgId: string) {
    await this.page.goto(
      `/dashboard/${orgId}/agents/${agentId}/configuration?section=webhooks`,
    );
  }

  async createWebhook(name: string) {
    await this.page.getByRole("button", { name: "Add webhook" }).click();
    await this.page.getByLabel("Webhook name").fill(name);
    await this.page
      .getByRole("combobox", { name: "Deliver results to" })
      .click();
    await this.page.getByRole("option", { name: /Acme Slack/ }).click();
    await this.page.getByRole("button", { name: /create webhook/i }).click();
  }

  signingSecret(): Locator {
    return this.page.getByRole("textbox", { name: "Signing secret" });
  }

  exampleRequest(): Locator {
    return this.page.locator("pre").filter({ hasText: "curl -X POST" });
  }

  acknowledgeSecretButton(): Locator {
    return this.page.getByRole("button", { name: "I've copied the secret" });
  }

  invocation(text: string): Locator {
    return this.page.getByRole("button", { name: new RegExp(text) });
  }

  retrySubmissionButton(): Locator {
    return this.page.getByRole("button", { name: "Retry submission" });
  }
}
