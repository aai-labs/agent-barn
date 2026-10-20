import type { Page } from "@playwright/test";

export class PlatformWorkflowSettingsPage {
  constructor(private page: Page) {}
  async goto() { await this.page.goto("/dashboard/platform/settings?section=workflows"); }
  toggle() { return this.page.getByRole("switch", { name: "Enable workflow authoring" }); }
  save() { return this.page.getByRole("button", { name: "Save", exact: true }); }
  async cancel() { await this.page.getByRole("button", { name: "Cancel", exact: true }).click(); }
}
