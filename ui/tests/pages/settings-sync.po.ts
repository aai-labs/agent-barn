import { Page, expect } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";

/** Locators and user actions for Settings → Sync. Assertions live in the spec. */
export class SettingsSyncPage {
  constructor(private page: Page) {}

  get heading() {
    return this.page.getByRole("heading", { name: "Sync", exact: true });
  }

  get section() {
    return this.page.getByRole("region", { name: "Sync" });
  }

  get sidebarItem() {
    return this.page.getByRole("button", { name: "Sync", exact: true });
  }

  get retry() {
    return this.page.getByRole("button", { name: /try again/i });
  }

  get rows() {
    return this.section.getByRole("listitem");
  }

  get dialog() {
    return this.page.getByRole("dialog");
  }

  row(name: string) {
    return this.section.getByRole("listitem", { name, exact: true });
  }

  connect(name: string) {
    return this.row(name).getByRole("button", { name: "Connect", exact: true });
  }

  openFolder(name: string) {
    return this.row(name).getByRole("link", { name: `Open in ${name}` });
  }

  disconnect(name: string) {
    return this.row(name).getByRole("button", { name: "Disconnect", exact: true });
  }

  approvalLink(name: string) {
    return this.row(name).getByRole("link", { name: "approval link" });
  }

  locationSearch(name: string, noun: string) {
    return this.row(name).getByRole("textbox", { name: `Search ${noun}s` });
  }

  searchButton(name: string) {
    return this.row(name).getByRole("button", { name: "Search", exact: true });
  }

  useLocation(name: string, location: string) {
    return this.row(name).getByRole("button", { name: `Use ${location}` });
  }

  startOver(name: string) {
    return this.row(name).getByRole("button", { name: "Start over" });
  }

  error(name: string) {
    return this.row(name).getByRole("alert");
  }

  async searchLocations(name: string, noun: string, term: string) {
    await this.locationSearch(name, noun).fill(term);
    await this.searchButton(name).click();
  }

  async confirmDisconnect(name: string) {
    await this.disconnect(name).click();
    await this.dialog.getByRole("button", { name: "Disconnect", exact: true }).click();
  }

  async open() {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/settings?tab=sync`);
    await expect(this.heading).toBeVisible();
  }
}
