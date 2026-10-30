import { type Page } from "@playwright/test";
import { workflowDraft } from "../fixtures/workflows";

export class WorkflowsPage {
  constructor(readonly page: Page) {}
  async goto(agentId: string, organizationId: string, workflowId?: string) {
    await this.page.goto(
      `/dashboard/${organizationId}/agents/${agentId}?tab=workflows${workflowId ? `&workflow=${workflowId}` : ""}`,
    );
  }
  async create(outcome: string) {
    await this.page.getByRole("button", { name: "+ Create workflow" }).click();
    await this.page.getByLabel("Description (optional)").fill(outcome);
  }
  async buildExample() {
    await this.page.getByLabel("Workflow name").fill(workflowDraft.name);
    for (const [index, step] of workflowDraft.steps.entries()) {
      if (index)
        await this.page.getByRole("button", { name: "Add a step" }).click();
      else await this.selectStep(1);
      const panel = this.step(index + 1);
      await panel
        .getByLabel(`Step ${index + 1}`, { exact: true })
        .fill(step.name);
      await panel.getByLabel("What should the Agent do?").fill(step.goal);
      if (step.artifact_description !== null) {
        await panel
          .getByLabel("Output from this step (optional)")
          .fill(step.artifact_description);
      }
    }
    await this.selectSection("Required inputs");
    for (const [index, input] of workflowDraft.inputs.entries()) {
      await this.page.getByRole("button", { name: "+ Add an input" }).click();
      await this.page.getByLabel(`Input ${index + 1} label`).fill(input.label);
      await this.page
        .getByLabel(`Input ${index + 1} description`)
        .fill(input.description);
    }
    await this.selectSection("Workflow details");
  }
  step(index: number) {
    return this.page.getByRole("region", {
      name: `Step ${index} editor`,
      exact: true,
    });
  }
  async selectStep(index: number) {
    await this.page
      .getByRole("navigation", { name: "Workflow sections" })
      .getByRole("button", { name: new RegExp(`^Step ${index}:`) })
      .click();
  }
  async selectSection(name: string) {
    await this.page
      .getByRole("navigation", { name: "Workflow sections" })
      .getByRole("button", { name, exact: true })
      .click();
  }
  async useFileInput() {
    await this.selectSection("Required inputs");
    await this.page.getByRole("combobox", { name: "Input 1 type" }).click();
    await this.page.getByRole("option", { name: "File", exact: true }).click();
  }
  async history() {
    await this.page.getByRole("tab", { name: "Version history" }).click();
  }
  async archive() {
    await this.page.getByRole("button", { name: "Workflow actions" }).click();
    await this.page.getByRole("menuitem", { name: "Archive workflow" }).click();
  }
  /** A section of the Agent in the navigation panel beside the page. */
  sectionLink(name: string) {
    return this.page.getByRole("complementary").getByRole("link", { name, exact: true });
  }
  async switchOrganization(name: string) {
    await this.page.getByRole("button", { name: /^Switch organization/ }).click();
    await this.page.getByRole("menuitem", { name: new RegExp(name, "i") }).click();
  }
  async save() {
    await this.page
      .getByRole("button", { name: "Save workflow", exact: true })
      .click();
  }
}
