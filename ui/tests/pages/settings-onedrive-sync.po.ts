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

  get connect() {
    return this.section.getByRole("button", { name: "Connect OneDrive" });
  }

  get siteSearch() {
    return this.section.getByRole("textbox", { name: "Search SharePoint sites" });
  }

  get searchButton() {
    return this.section.getByRole("button", { name: "Search", exact: true });
  }

  get error() {
    return this.section.getByRole("alert");
  }

  get disconnect() {
    return this.section.getByRole("button", { name: "Disconnect", exact: true });
  }

  get startOver() {
    return this.section.getByRole("button", { name: "Start over" });
  }

  get dialog() {
    return this.page.getByRole("dialog");
  }

  async confirmDisconnect() {
    await this.disconnect.click();
    await this.dialog.getByRole("button", { name: "Disconnect", exact: true }).click();
  }

  useSite(name: string) {
    return this.section.getByRole("button", { name: `Use ${name}` });
  }

  async searchSites(term: string) {
    await this.siteSearch.fill(term);
    await this.searchButton.click();
  }

  async open() {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/settings?tab=onedrive-sync`);
    await expect(this.heading).toBeVisible();
  }
}
