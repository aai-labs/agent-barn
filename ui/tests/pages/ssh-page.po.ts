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
    await this.addButton().click();
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
  savedDialog() {
    return this.page.getByRole("dialog", { name: "SSH credential saved" });
  }
  publicKey() {
    return this.page.getByLabel("SSH public key");
  }
  privateKey() {
    return this.page.getByRole("textbox", { name: "Private key", exact: true });
  }
  editorError() {
    return this.editor().getByRole("alert");
  }
  credentialButton(name: string) {
    return this.page.getByRole("button", { name, exact: false });
  }
  addButton() {
    return this.page.getByRole("button", { name: "Add SSH credential", exact: true });
  }
  editButton() {
    return this.section().getByRole("button", { name: "Edit", exact: true });
  }
  assignmentCheckbox() {
    return this.section().getByRole("checkbox");
  }
  assignmentError() {
    return this.section().getByRole("alert");
  }
  applyButton() {
    return this.section().getByRole("button", { name: "Apply & Restart", exact: true });
  }
  restartDialog() {
    return this.page.getByRole("dialog");
  }
  async enterPrivateKey(key: string, passphrase: string) {
    await this.privateKey().fill(key);
    await this.editor().getByLabel("Passphrase (optional)").fill(passphrase);
  }
  async editAssignments() {
    await this.editButton().click();
  }
  async detachKey() {
    await this.assignmentCheckbox().uncheck();
  }
  async requestApply() {
    await this.applyButton().click();
  }
  async confirmRestart() {
    await this.restartDialog().getByRole("button", { name: "Apply & Restart", exact: true }).click();
  }
  async applyAssignments() {
    await this.requestApply();
    await this.confirmRestart();
  }
}
