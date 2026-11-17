import type { Page } from "@playwright/test";

export class PlatformLlmProvidersPage {
  constructor(private page: Page) {}

  async goto() {
    await this.page.goto("/dashboard/platform/settings?section=llm-providers");
  }

  card() {
    return this.page.getByRole("region", { name: "OpenRouter" });
  }

  openDialogButton() {
    return this.card().getByRole("button", { name: /^(Replace key|Save a key)$/ });
  }

  dialog() {
    return this.page.getByRole("dialog");
  }

  keyInput() {
    return this.dialog().getByLabel("OpenRouter API key");
  }

  async submitKey(key: string) {
    await this.openDialogButton().click();
    await this.keyInput().fill(key);
    await this.dialog().getByRole("button", { name: "Save key" }).click();
  }

  async cancelDialog() {
    await this.dialog().getByRole("button", { name: "Cancel" }).click();
  }
}
