import { expect, test } from "@playwright/test";
import { DataSupport } from "../pages/data-support/data-support.po";
import { MOCK_AGENT_ID, mockAgent } from "../pages/data-support/agent-data-support.po";
import { ArtifactDataSupport } from "../pages/data-support/artifact-data-support.po";
import { AgentFilesPage } from "../pages/agent-files-page.po";
import { WorkflowDataSupport } from "../pages/data-support/workflow-data-support.po";
import { WorkflowRunDataSupport, RUN_ID } from "../pages/data-support/workflow-run-data-support.po";
import { WorkflowRunsPage } from "../pages/workflow-runs-page.po";
import { artifactFixture, fileIconFixtures } from "../fixtures/artifacts";
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
  test("download links reject non-HTTP URL schemes", async ({page}) => {
    const files = new AgentFilesPage(page);
    await files.goto(MOCK_AGENT_ID);
    await expect(files.files).toContainText("pipeline.csv");
    support.downloadUrl = "javascript:alert(1)";
    await files.download("pipeline.csv");
    await expect(page.getByText("Download is unavailable", {exact: true})).toBeVisible();
    await expect(page).toHaveURL(/tab=files/);
  });
  test("run and selected step retain attachments alongside text summaries", async ({page}) => {
    await new WorkflowDataSupport(page).intercept(MOCK_AGENT_ID, {saved: true});
    const runs = new WorkflowRunDataSupport(page); runs.state = "SUCCEEDED"; await runs.intercept(MOCK_AGENT_ID);
    await support.intercept(MOCK_AGENT_ID);
    const stepId = workflowFixture(MOCK_AGENT_ID).version.draft.steps[0].id;
    support.files = [{...artifactFixture, source: "workflow", run_id: RUN_ID, step_id: stepId, attempt_id: "a4150000-0000-4000-8000-000000000002"}];
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
    await expect(page.getByLabel("Run files", {exact: true})).toContainText("pipeline.csv");
    await page.getByRole("button", {name: "Step 1: Read pipeline"}).click();
    await expect(page.getByLabel("Step files", {exact: true})).toContainText("pipeline.csv");
    await expect(page.getByText("Finished read pipeline.", {exact: true})).toBeVisible();
    await expect(page.getByLabel("Step files", {exact: true})).toContainText("attempt a4150000");
    const requests = support.lists;
    await page.waitForTimeout(5500);
    expect(support.lists).toBe(requests);
  });
  test("existing Agents can provision and see progress until ready", async ({page}, testInfo) => {
    await new DataSupport(page).agents.interceptGetAgentRequest({body: {...mockAgent, allowed_actions: ["agent.read", "agent.update"]}});
    support.storageState = "NOT_PROVISIONED";
    support.files = [];
    const files = new AgentFilesPage(page); await files.goto(MOCK_AGENT_ID);
    await expect(files.files).toContainText("Artifact Storage Not Provisioned");
    await files.files.screenshot({path: testInfo.outputPath("storage-not-provisioned.png")});
    await files.provision();
    await expect(files.files).toContainText("Provisioning artifact storage…");
    await files.files.screenshot({path: testInfo.outputPath("storage-provisioning.png")});
    await expect(files.provisionButton).toHaveCount(0);
    expect(support.provisionRequests).toBe(1);
    support.storageState = "READY";
    await expect(files.files).toContainText("No published files yet.");
    await expect(files.files).not.toContainText("Provisioning artifact storage…");
  });
  test("readers see missing storage without a provisioning action", async ({page}) => {
    support.storageState = "NOT_PROVISIONED";
    const files = new AgentFilesPage(page); await files.goto(MOCK_AGENT_ID);
    await expect(files.files).toContainText("Artifact Storage Not Provisioned");
    await expect(files.provisionButton).toHaveCount(0);
    await expect(files.files).toContainText("Ask someone with Agent update access");
  });
  test("provisioning failure can be retried", async ({page}, testInfo) => {
    await new DataSupport(page).agents.interceptGetAgentRequest({body: {...mockAgent, allowed_actions: ["agent.read", "agent.update"]}});
    support.storageState = "FAILED";
    const files = new AgentFilesPage(page); await files.goto(MOCK_AGENT_ID);
    await expect(files.files).toContainText("Artifact storage provisioning failed");
    await files.files.screenshot({path: testInfo.outputPath("storage-retry.png")});
    await files.retryProvisioning();
    await expect(files.files).toContainText("Provisioning artifact storage…");
    support.storageState = "READY";
    await expect(files.files).not.toContainText("Provisioning artifact storage…");
    expect(support.provisionRequests).toBe(1);
  });
  test("permission loss during provision shows an inline error", async ({page}) => {
    await new DataSupport(page).agents.interceptGetAgentRequest({body: {...mockAgent, allowed_actions: ["agent.read", "agent.update"]}});
    support.storageState = "NOT_PROVISIONED";
    support.provisionDenied = true;
    const files = new AgentFilesPage(page); await files.goto(MOCK_AGENT_ID);
    await files.provision();
    await expect(files.files).toContainText("Provisioning could not be requested");
    await expect(files.files).not.toContainText("Provisioning artifact storage…");
  });

  test("files load more on scroll and retain earlier downloads", async ({page}) => {
    support.files = Array.from({length: 45}, (_, index) => ({...artifactFixture, id: `file-${index}`, filename: `report-${index + 1}.csv`}));
    const files = new AgentFilesPage(page); await files.goto(MOCK_AGENT_ID);
    await expect(files.files.locator("li")).toHaveCount(20);
    await files.scrollToLastFile();
    await expect(files.files.locator("li")).toHaveCount(40);
    await files.scrollToLastFile();
    await expect(files.files.locator("li")).toHaveCount(45);
    await expect(files.files).toContainText("report-1.csv");
    await expect(files.files).toContainText("report-45.csv");
    expect(support.requestedPages).toEqual([1, 2, 3]);
    await expect(page.getByRole("button", {name: "Next files"})).toHaveCount(0);
    const pending = page.waitForEvent("download"); await files.download("report-1.csv"); await pending;
  });
  test("a legacy file shows its specific error without blocking newer downloads", async ({page}, testInfo) => {
    support.files = [{...artifactFixture, filename: "older-report.csv"}, {...artifactFixture, id: "current-file", filename: "new-report.csv"}];
    support.downloadFailure = {id: artifactFixture.id, status: 409, detail: "This file uses the previous storage layout and has not been migrated. It must be migrated or uploaded again before downloading. Newer files are unaffected."};
    const files = new AgentFilesPage(page); await files.goto(MOCK_AGENT_ID);
    await files.download("older-report.csv");
    const failed = files.files.getByRole("alert");
    await expect(failed).toContainText("previous storage layout");
    await expect(failed).not.toContainText("Artifact storage is unavailable");
    await files.files.screenshot({path: testInfo.outputPath("legacy-file-download-error.png")});
    const pending = page.waitForEvent("download"); await files.download("new-report.csv"); await pending;
    await expect(failed).toHaveCount(0);
  });

  test("a load-more failure retains loaded files and can be retried", async ({page}) => {
    support.files = Array.from({length: 25}, (_, index) => ({...artifactFixture, id: `file-${index}`, filename: `report-${index + 1}.csv`}));
    support.failPage = 2;
    const files = new AgentFilesPage(page); await files.goto(MOCK_AGENT_ID);
    await expect(files.files.locator("li")).toHaveCount(20);
    await files.scrollToLastFile();
    await expect(files.files).toContainText("More files could not be loaded");
    await expect(files.files.locator("li")).toHaveCount(20);
    support.failPage = undefined;
    await files.retryMoreFiles();
    await expect(files.files.locator("li")).toHaveCount(25);
    await expect(files.files).not.toContainText("More files could not be loaded");
  });

  test("file rows show recognizable types and a generic fallback", async ({page}, testInfo) => {
    support.files = fileIconFixtures;
    const files = new AgentFilesPage(page); await files.goto(MOCK_AGENT_ID);
    for (const label of ["PDF file", "Spreadsheet file", "Image file", "Archive file", "Generic file"]) {
      await expect(files.files.getByRole("img", {name: label, exact: true})).toBeVisible();
    }
    await expect(files.files.getByRole("button", {name: "Download quarterly-report.pdf"})).toBeVisible();
    await files.files.screenshot({path: testInfo.outputPath("file-list-icons.png")});
  });

  test("editors confirm deletion and the list updates", async ({page}) => {
    await new DataSupport(page).agents.interceptGetAgentRequest({body: {...mockAgent, allowed_actions: ["agent.read", "agent.update"]}});
    const files = new AgentFilesPage(page); await files.goto(MOCK_AGENT_ID);
    await files.delete("pipeline.csv");
    await expect(files.deleteDialog).toContainText("pipeline.csv");
    expect(support.deleteRequests).toBe(0);
    await files.cancelDelete();
    await expect(files.deleteDialog).toHaveCount(0);
    expect(support.deleteRequests).toBe(0);
    await files.delete("pipeline.csv");
    await files.confirmDelete();
    await expect(files.deleteDialog).toHaveCount(0);
    await expect(files.files).toContainText("No published files yet.");
    await expect(files.files.locator("li")).toHaveCount(0);
    expect(support.deleteRequests).toBe(1);
  });
  test("readers cannot see delete controls", async ({page}) => {
    const files = new AgentFilesPage(page); await files.goto(MOCK_AGENT_ID);
    await expect(files.files).toContainText("pipeline.csv");
    await expect(files.files.getByRole("button", {name: "Delete pipeline.csv", exact: true})).toHaveCount(0);
  });
  test("a pinned file cannot be deleted and the dialog explains why", async ({page}) => {
    await new DataSupport(page).agents.interceptGetAgentRequest({body: {...mockAgent, allowed_actions: ["agent.read", "agent.update"]}});
    support.deleteFailure = {status: 409, detail: "An active run or review pins this file"};
    const files = new AgentFilesPage(page); await files.goto(MOCK_AGENT_ID);
    await files.delete("pipeline.csv"); await files.confirmDelete();
    await expect(files.deleteDialog).toContainText("An active run or review pins this file");
    await files.cancelDelete();
    await expect(files.files).toContainText("pipeline.csv");
    support.deleteFailure = undefined;
    await files.delete("pipeline.csv");
    await files.confirmDelete();
    await expect(files.deleteDialog).toHaveCount(0);
    await expect(files.files.locator("li")).toHaveCount(0);
  });
  test("permission loss during deletion preserves the file", async ({page}) => {
    await new DataSupport(page).agents.interceptGetAgentRequest({body: {...mockAgent, allowed_actions: ["agent.read", "agent.update"]}});
    support.deleteFailure = {status: 403, detail: "Agent update permission required"};
    const files = new AgentFilesPage(page); await files.goto(MOCK_AGENT_ID);
    await files.delete("pipeline.csv"); await files.confirmDelete();
    await expect(files.deleteDialog).toContainText("File could not be deleted");
    await files.cancelDelete();
    await expect(files.deleteDialog).toHaveCount(0);
    await expect(files.files).toContainText("pipeline.csv");
  });

});
