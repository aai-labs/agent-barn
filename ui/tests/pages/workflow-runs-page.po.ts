import { type Page } from "@playwright/test";
import { TEST_ORG_ID } from "../constants";
import { WORKFLOW_ID } from "../fixtures/workflows";
import { RUN_ID } from "./data-support/workflow-run-data-support.po";

export class WorkflowRunsPage {
  constructor(private page: Page) {}
  /** A run on its Agent's page, or the saved workflow on the Organization's Workflows page. */
  async goto(agentId: string, run = false, organizationId = TEST_ORG_ID) {
    await this.page.goto(
      run
        ? `/dashboard/${organizationId}/agents/${agentId}?tab=workflows&workflowRun=${RUN_ID}`
        : `/dashboard/${organizationId}/workflows?workflow=${WORKFLOW_ID}`,
    );
  }
  /** The Organization's Workflows page, which opens on its Runs tab. */
  async gotoLanding(query = "") {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/workflows${query}`);
  }
  /** A run opened from the Organization's Workflows page. */
  async gotoOrganizationRun() {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/workflows?workflowRun=${RUN_ID}`);
  }
  /** An Agent's Workflows tab: its own runs. */
  async gotoAgentRuns(agentId: string) {
    await this.page.goto(`/dashboard/${TEST_ORG_ID}/agents/${agentId}?tab=workflows`);
  }
  async selectView(name: "Overview" | "Version history" | "Runs") {
    await this.page.getByRole("tab", { name, exact: true }).click();
  }
  /** A section of runs: "Active", "Recent", or an Agent's "Recent runs". */
  runs(section: string) {
    return this.page.getByRole("region", { name: section, exact: true });
  }
  async openFirstRun(section = "Recent") {
    await this.runs(section).getByRole("button").first().click();
  }
  async gotoView(view: string) {
    await this.page.goto(
      `/dashboard/${TEST_ORG_ID}/workflows?workflow=${WORKFLOW_ID}&workflowView=${view}`,
    );
  }
  /** The Run dialog, opened from the saved workflow. */
  dialog() {
    return this.page.getByRole("dialog");
  }
  async openRunDialog() {
    await this.page.getByRole("button", { name: "Run workflow", exact: true }).click();
  }
  /** The Agent chips under "Run as". */
  runAs(name: string) {
    return this.dialog().getByRole("radio", { name, exact: true });
  }
  async chooseAgent(name: string) {
    await this.runAs(name).click();
  }
  /** Opens the Run dialog, chooses the Agent and fills the text input. */
  async reviewInputs(period: string, agent = "Maya") {
    await this.openInputReview(agent);
    await this.page.getByLabel("Reporting period (required)").fill(period);
  }
  async openInputReview(agent = "Maya") {
    await this.openRunDialog();
    await this.chooseAgent(agent);
  }
  async selectFile(label: string, filename: string) {
    await this.page.getByRole("combobox", { name: `Select file for ${label}` }).click();
    await this.page.getByRole("option", { name: new RegExp(filename) }).click();
  }
  async uploadFile(label: string, bytes: Buffer) {
    await this.page.getByLabel(`Upload file for ${label}`).setInputFiles({ name: "uploaded.csv", mimeType: "text/csv", buffer: bytes });
  }
  async runAgain() {
    // The closing confirmation dialog retains another Run again button.
    await this.page
      .getByRole("region", { name: "Run detail", exact: true })
      .getByRole("button", { name: "Run again", exact: true })
      .click();
  }
  async confirmRunAgain() {
    await this.page
      .getByRole("dialog")
      .getByRole("button", { name: "Run again", exact: true })
      .click();
  }
  async start() {
    await this.page.getByRole("button", { name: "Start run", exact: true }).click();
  }
  async selectedViewGeometry() {
    return {
      panel: await this.page.getByLabel("Selected run view", { exact: true }).boundingBox(),
      connector: await this.page.getByTestId("run-view-connector").boundingBox(),
    };
  }
  async stepConnectorGeometry() {
    const rail = this.page.getByLabel("Step progress");
    return {
      first: await rail.getByTestId("step-marker").nth(0).boundingBox(),
      second: await rail.getByTestId("step-marker").nth(1).boundingBox(),
      connector: await rail.getByTestId("step-connector").first().boundingBox(),
    };
  }
  async showArtifacts() {
    await this.page.getByRole("button", { name: "All artifacts", exact: true }).click();
  }
  async backToRuns() {
    await this.page
      .getByRole("button", { name: "All workflows", exact: true })
      .click();
  }
  async selectStep(name: string) {
    await this.page
      .getByLabel("Step progress")
      .getByRole("button", { name, exact: true })
      .click();
  }
  async showSummary() {
    await this.page
      .getByRole("button", { name: /^(Result ready|Run overview)$/ })
      .click();
  }
  async cancel() {
    await this.page
      .getByRole("button", { name: "Cancel run", exact: true })
      .click();
    await this.page
      .getByRole("dialog")
      .getByRole("button", { name: "Cancel run", exact: true })
      .click();
  }
}
