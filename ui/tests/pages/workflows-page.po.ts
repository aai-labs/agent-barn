import { type Page } from "@playwright/test";

import { TEST_ORG_ID } from "../constants";
import { workflowDraft } from "../fixtures/workflows";

/** The Organization's Workflows page: its saved workflows and the editor dialog. */
export class WorkflowsPage {
  constructor(readonly page: Page) {}
  /** The saved workflows list, or one saved workflow when its id is given. */
  async goto(organizationId = TEST_ORG_ID, workflowId?: string) {
    await this.page.goto(
      `/dashboard/${organizationId}/workflows?${workflowId ? `workflow=${workflowId}` : "workflowsTab=workflows"}`,
    );
  }
  /** The editor, opened over the page. */
  editor() {
    return this.page.getByRole("dialog", {
      name: /^(Design a reusable workflow|Refine the workflow)$/,
    });
  }
  /** A branded confirmation, opened over the page or the editor. */
  confirmation(title: RegExp) {
    return this.page.getByRole("dialog", { name: title });
  }
  async create(purpose?: string) {
    await this.page.getByRole("button", { name: "New workflow" }).click();
    if (purpose) await this.purpose().fill(purpose);
  }
  name() {
    return this.editor().getByLabel("Name", { exact: true });
  }
  purpose() {
    return this.editor().getByLabel("What does it do?");
  }
  step(index: number) {
    return this.editor().getByRole("listitem", { name: `Step ${index}`, exact: true });
  }
  stepInstructions(index: number) {
    return this.editor().getByLabel(`Step ${index} instructions`, { exact: true });
  }
  async addStep() {
    await this.editor().getByRole("button", { name: "Add step" }).click();
  }
  async addInput() {
    await this.editor().getByRole("button", { name: "Add input" }).click();
  }
  /** Fills the form with the example workflow: its name, steps and one input. */
  async buildExample() {
    await this.name().fill(workflowDraft.name);
    for (const [index, step] of workflowDraft.steps.entries()) {
      if (index) await this.addStep();
      await this.stepInstructions(index + 1).fill(step.goal);
    }
    for (const [index, input] of workflowDraft.inputs.entries()) {
      await this.addInput();
      await this.editor().getByLabel(`Input ${index + 1} label`).fill(input.label);
      await this.editor()
        .getByLabel(`Input ${index + 1} description`)
        .fill(input.description);
    }
  }
  async useFileInput() {
    await this.editor().getByRole("combobox", { name: "Input 1 type" }).click();
    await this.page.getByRole("option", { name: "File", exact: true }).click();
  }
  /** The default Agent chips; "No default" clears it. */
  defaultAgent(name: string) {
    return this.editor()
      .getByRole("radiogroup", { name: /Default agent/ })
      .getByRole("radio", { name, exact: true });
  }
  async save() {
    await this.editor()
      .getByRole("button", { name: /^Save (workflow|changes)$/ })
      .click();
  }
  saveButton() {
    return this.editor().getByRole("button", { name: /^Save (workflow|changes)$/ });
  }
  error() {
    return this.editor().getByRole("alert", { name: "Workflow error" });
  }
  card(name: string) {
    return this.page.getByRole("article", { name, exact: true });
  }
  async cardAction(name: string, action: string) {
    await this.card(name).getByRole("button", { name: `Actions for ${name}` }).click();
    await this.page.getByRole("menuitem", { name: action, exact: true }).click();
  }
  async open(name: string) {
    await this.page.getByRole("button", { name: `Open ${name}`, exact: true }).click();
  }
  /** Toggle between the active workflows and the archived ones. */
  async toggleArchived() {
    await this.page
      .getByRole("region", { name: "Saved workflows" })
      .getByRole("button", { name: /^(Show archived|Back to workflows)$/ })
      .click();
  }
  async edit() {
    await this.page.getByRole("button", { name: "Edit workflow" }).click();
  }
  async history() {
    await this.page.getByRole("tab", { name: "Version history" }).click();
  }
  async backToList() {
    await this.page.getByRole("button", { name: "All workflows", exact: true }).click();
  }
  async archive() {
    await this.page.getByRole("button", { name: "Workflow actions" }).click();
    await this.page.getByRole("menuitem", { name: "Archive workflow" }).click();
  }
  async confirmArchive() {
    await this.confirmation(/^Archive /)
      .getByRole("button", { name: "Archive workflow", exact: true })
      .click();
  }
  /** The Organization's Workflows destination in the navigation rail. */
  railLink() {
    return this.page.locator('a[href$="/workflows"]:visible', { hasText: "Workflows" });
  }
  /** A section of an Agent in the navigation panel beside the page. */
  sectionLink(name: string) {
    return this.page.getByRole("complementary").getByRole("link", { name, exact: true });
  }
  async switchOrganization(name: string) {
    await this.page.getByRole("button", { name: /^Switch organization/ }).click();
    await this.page.getByRole("menuitem", { name: new RegExp(name, "i") }).click();
  }
}
