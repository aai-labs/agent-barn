import { Page, expect } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";

/** Locators and user actions for Settings → OneDrive. Assertions live in the spec. */
export class SettingsOneDriveSyncPage {
  constructor(private page: Page) {}

  get heading() {
    return this.page.getByRole("heading", { name: "OneDrive", exact: true });
  }

  get section() {
    return this.page.getByRole("region", { name: "OneDrive" });
  }

  get sidebarItem() {
    return this.page.getByRole("button", { name: "OneDrive", exact: true });
  }

  get openInOneDrive() {
    return this.section.getByRole("link", { name: "Open in OneDrive" });
  }

  get retry() {
    return this.page.getByRole("button", { name: /try again/i });
  }

  async open() {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/settings?tab=onedrive-sync`);
    await expect(this.heading).toBeVisible();
  }
}
