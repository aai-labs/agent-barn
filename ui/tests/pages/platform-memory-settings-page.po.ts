import { Page } from "@playwright/test";

export class PlatformMemorySettingsPage {
  constructor(private page: Page) {}
  async goto() { await this.page.goto("/dashboard/platform/settings"); }
  model() { return this.page.getByRole("combobox", { name: "Memory processing model" }); }
  save() { return this.page.getByRole("button", { name: "Save", exact: true }); }
  async choose(name: string) {
    await this.model().click();
    await this.page.getByPlaceholder("Search memory models…").fill(name);
    await this.page.getByRole("option", { name }).click();
  }
  async intercept({ readStatus = 200, saveStatus = 200, modelsStatus = 200 } = {}) {
    let model = "openrouter/openai/gpt-4.1-mini";
    const writes: unknown[] = [];
    const reads: string[] = [];
    let failure = saveStatus;
    await this.page.route("**/api/v1/platform/settings/agent-memory/models", (route) => { reads.push("models"); return route.fulfill({
      status: modelsStatus, contentType: "application/json",
      body: JSON.stringify(modelsStatus === 200 ? [
        { value: "openrouter/openai/gpt-4.1-mini", label: "GPT-4.1 mini" },
        { value: "openrouter/anthropic/alternate", label: "Alternate model" },
      ] : { detail: "Model catalog unavailable" }),
    }); });
    await this.page.route("**/api/v1/platform/settings/agent-memory", async (route) => {
      if (route.request().method() === "GET") reads.push("settings");
      if (route.request().method() === "PUT") {
        const payload = route.request().postDataJSON();
        writes.push(payload);
        if (failure >= 400) return route.fulfill({ status: failure, contentType: "application/json", body: JSON.stringify({ detail: "The model could not be enabled. Your setting was not changed." }) });
        model = payload.model;
      }
      return route.fulfill({ status: readStatus, contentType: "application/json", body: JSON.stringify(readStatus === 200 ? { model, updated_at: null } : { detail: "Settings unavailable" }) });
    });
    return { writes, reads, allowSave: () => { failure = 200; } };
  }
}
