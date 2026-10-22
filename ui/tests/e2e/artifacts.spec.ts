import { expect, test } from "@playwright/test";
import { DataSupport } from "../pages/data-support/data-support.po";
import { MOCK_AGENT_ID, mockAgent } from "../pages/data-support/agent-data-support.po";
import { ArtifactDataSupport } from "../pages/data-support/artifact-data-support.po";
import { AgentFilesPage } from "../pages/agent-files-page.po";
import { WorkflowDataSupport } from "../pages/data-support/workflow-data-support.po";
import { WorkflowRunDataSupport, RUN_ID } from "../pages/data-support/workflow-run-data-support.po";
import { WorkflowRunsPage } from "../pages/workflow-runs-page.po";
import { artifactFixture } from "../fixtures/artifacts";
import { workflowFixture } from "../fixtures/workflows";

test.describe("Agent artifacts", () => {
  test.use({storageState: {cookies: [], origins: []}});
  let support: ArtifactDataSupport;
  test.beforeEach(async ({page}) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.agents.interceptGetAgentRequest({body: {...mockAgent, allowed_actions: ["agent.read"]}});
    support = new ArtifactDataSupport(page); await support.intercept(MOCK_AGENT_ID);
  });
  test("read-only Agent readers download using a fresh link on every click", async ({page}) => {
    const files = new AgentFilesPage(page); await files.goto(MOCK_AGENT_ID);
    await expect(files.files).toContainText("pipeline.csv");
    await expect(files.files).toContainText("24 bytes");
    for (let i = 0; i < 2; i++) {
      const download = page.waitForEvent("download"); await files.download("pipeline.csv");
      expect((await download).suggestedFilename()).toBe("pipeline.csv");
    }
    expect(support.links).toBe(2);
  });
  test("access loss prevents link issuance and shows a truthful error", async ({page}) => {
    const files = new AgentFilesPage(page); await files.goto(MOCK_AGENT_ID);
    await expect(files.files).toContainText("pipeline.csv"); support.denied = true;
    await files.download("pipeline.csv");
    await expect(page.getByText("Download is unavailable", {exact: true})).toBeVisible();
    expect(support.links).toBe(0);
  });
  test("run and selected step retain attachments alongside text summaries", async ({page}) => {
    await new WorkflowDataSupport(page).intercept(MOCK_AGENT_ID, {saved: true});
    const runs = new WorkflowRunDataSupport(page); runs.state = "SUCCEEDED"; await runs.intercept(MOCK_AGENT_ID);
    await support.intercept(MOCK_AGENT_ID);
    const stepId = workflowFixture(MOCK_AGENT_ID).version.draft.steps[0].id;
    support.files = [{...artifactFixture, source: "workflow", run_id: RUN_ID, step_id: stepId}];
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
    await expect(page.getByLabel("Run files", {exact: true})).toContainText("pipeline.csv");
    await page.getByRole("button", {name: "Step 1: Read pipeline"}).click();
    await expect(page.getByLabel("Step files", {exact: true})).toContainText("pipeline.csv");
    await expect(page.getByText("Finished read pipeline.", {exact: true})).toBeVisible();
  });
});
