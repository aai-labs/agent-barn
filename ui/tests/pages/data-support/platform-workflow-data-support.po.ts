import type { Page } from "@playwright/test";

export class PlatformWorkflowDataSupport {
  constructor(private page: Page) {}
  async intercept(options: { saveStatus?: number; readStatus?: number } = {}) {
    let enabled = false;
    let saveStatus = options.saveStatus ?? 200;
    let readStatus = options.readStatus ?? 200;
    const writes: unknown[] = [];
    const reads: string[] = [];
    await this.page.route("**/api/v1/platform/settings/workflows", async (route) => {
      const writing = route.request().method() === "PUT";
      if (writing) writes.push(route.request().postDataJSON());
      else reads.push("settings");
      const status = writing ? saveStatus : readStatus;
      if (status >= 400) return route.fulfill({
        status, contentType: "application/json",
        body: JSON.stringify({ detail: "Workflow settings are unavailable. Try again." }),
      });
      if (writing) enabled = route.request().postDataJSON().authoring_enabled;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ authoring_enabled: enabled, updated_at: null }) });
    });
    return { writes, reads, recover: () => { saveStatus = 200; readStatus = 200; } };
  }
}
