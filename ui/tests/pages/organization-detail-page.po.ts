import { Page } from "@playwright/test";

export class OrganizationDetailPage {
  constructor(private page: Page) {}
  get dialog() { return this.page.getByRole("dialog"); }
  get name() { return this.dialog.getByLabel("Organization name", { exact: true }); }
  get save() { return this.dialog.getByRole("button", { name: "Save name" }); }
  async openRename() {
    await this.page.getByRole("button", { name: "Rename organization", exact: true }).click();
  }
  async rename(name: string) {
    await this.name.fill(name);
    await this.save.click();
  }
  async cancel() {
    await this.dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  }
}
