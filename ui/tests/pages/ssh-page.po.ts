import type { Page } from "@playwright/test";

export class SshPage {
  constructor(private page: Page) {}
  editor() {
    return this.page.getByRole("dialog", {
      name: "Add SSH credential",
      exact: true,
    });
  }
  section() {
    return this.page.getByRole("region", { name: "SSH access", exact: true });
  }
  async addGenerated(name: string) {
    await this.page
      .getByRole("button", { name: "Add SSH credential", exact: true })
      .click();
    await this.editor().getByLabel("Name", { exact: true }).fill(name);
  }
  async save() {
    await this.editor()
      .getByRole("button", { name: "Save SSH credential", exact: true })
      .click();
  }
  async chooseImport() {
    await this.editor().getByRole("combobox", { name: "Key setup" }).click();
    await this.page
      .getByRole("option", { name: "Import existing private key" })
      .click();
  }
  async chooseUnrestricted() {
    await this.editor()
      .getByRole("combobox", { name: "Where this key can be used" })
      .click();
    await this.page
      .getByRole("option", { name: "Unrestricted", exact: true })
      .click();
  }
  async applyAssignments() {
    await this.section()
      .getByRole("button", { name: "Apply & Restart", exact: true })
      .click();
    await this.page
      .getByRole("dialog")
      .getByRole("button", { name: "Apply & Restart", exact: true })
      .click();
  }
}
