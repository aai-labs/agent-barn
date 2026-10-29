import { type Page } from "@playwright/test";
import { TEST_ORG_ID } from "../constants";
import { WORKFLOW_ID } from "../fixtures/workflows";
import { RUN_ID } from "./data-support/workflow-run-data-support.po";

export class WorkflowRunsPage {
  constructor(private page: Page) {}
  async goto(agentId: string, run = false, organizationId = TEST_ORG_ID) {
    await this.page.goto(
      `/dashboard/${organizationId}/agents/${agentId}?tab=workflows&workflow=${WORKFLOW_ID}${run ? `&workflowRun=${RUN_ID}` : ""}`,
    );
  }
  async selectView(name: "Overview" | "Runs" | "Version history") {
    await this.page.getByRole("tab", { name, exact: true }).click();
  }
  async openFirstRun() {
    await this.page
      .getByLabel("Workflow runs", { exact: true })
      .getByRole("button")
      .first()
      .click();
  }
  async gotoView(agentId: string, view: string) {
    await this.page.goto(
      `/dashboard/${TEST_ORG_ID}/agents/${agentId}?tab=workflows&workflow=${WORKFLOW_ID}&workflowView=${view}`,
    );
  }
  async reviewInputs(period: string) {
    await this.page
      .getByRole("button", { name: "Run workflow", exact: true })
      .click();
    await this.page.getByLabel("Reporting period (required)").fill(period);
  }
  async runAgain() {
    await this.page
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
    await this.page.getByRole("button", { name: /^Start run/ }).click();
  }
  async stepConnectorGeometry() {
    const rail = this.page.getByLabel("Step progress");
    return {
      first: await rail.getByTestId("step-marker").nth(0).boundingBox(),
      second: await rail.getByTestId("step-marker").nth(1).boundingBox(),
      connector: await rail.getByTestId("step-connector").first().boundingBox(),
    };
  }
  async backToRuns() {
    await this.page
      .getByRole("button", { name: "Back to runs", exact: true })
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
