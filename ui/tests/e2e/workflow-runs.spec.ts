import { expect, test } from "@playwright/test";
import { TEST_ORG_ID } from "../constants";
import { DataSupport } from "../pages/data-support/data-support.po";
import {
  MOCK_AGENT_ID,
  mockAgent,
} from "../pages/data-support/agent-data-support.po";
import { WorkflowDataSupport } from "../pages/data-support/workflow-data-support.po";
import {
  RERUN_ID,
  RUN_ID,
  WorkflowRunDataSupport,
} from "../pages/data-support/workflow-run-data-support.po";
import { WorkflowRunsPage } from "../pages/workflow-runs-page.po";
import { WorkflowsPage } from "../pages/workflows-page.po";
import { artifactFixture } from "../fixtures/artifacts";
import { WORKFLOW_ID } from "../fixtures/workflows";

test.describe("WF02 run progress and text results", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  let support: WorkflowRunDataSupport;
  test.beforeEach(async ({ page }) => {
    const data = new DataSupport(page);
    await data.auth.interceptRefreshRequest();
    await data.users.interceptGetUserContextRequest();
    await data.users.interceptGetOrganizationsRequest();
    await data.agents.interceptGetAgentRequest({ body: mockAgent });
    await data.agents.interceptGetAgentsRequest();
    await new WorkflowDataSupport(page).intercept(MOCK_AGENT_ID, {
      saved: true,
    });
    support = new WorkflowRunDataSupport(page);
    await support.intercept(MOCK_AGENT_ID);
  });
  test("file inputs expose provisioning and enforce the configured limit", async ({ page }) => {
    support.fileInputs = true;
    support.storageState = "NOT_PROVISIONED";
    support.storageLimit = 8;
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID);
    await runs.openInputReview();
    await expect(page.getByText("Artifact storage is not provisioned.")).toBeVisible();
    await page.getByRole("button", { name: "Provision storage" }).click();
    await expect(page.getByText("Artifact storage is being prepared.")).toBeVisible();
    expect(support.provisionRequests).toBe(1);
    support.storageState = "READY";
    await expect(page.getByText(/file up to 8 bytes/)).toBeVisible({ timeout: 10000 });
    await runs.uploadFile("Reporting period", Buffer.from("123456789"));
    await expect(page.getByText("Files must be at most 8 bytes", { exact: true })).toBeVisible();
    expect(support.uploadedBytes).toBeNull();
  });

  test("selects an existing file and retains exact references across start retries", async ({ page }) => {
    support.fileInputs = true;
    support.failStart = true;
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID);
    await runs.openInputReview();
    await runs.selectFile("Reporting period", "pipeline.csv");
    await runs.start();
    await expect(page.getByText("The run could not be started. Your inputs are retained.")).toBeVisible();
    await runs.start();
    await expect(page.getByLabel("Run detail")).toBeVisible();
    expect(support.starts).toHaveLength(2);
    expect(support.starts[1]).toEqual(support.starts[0]);
    expect(support.starts[0]).toMatchObject({ inputs: { period: { artifact_id: artifactFixture.id, checksum: artifactFixture.checksum } } });
    await expect(page.getByLabel("Run input files")).toContainText("pipeline.csv");
  });

  test("attachment picker uses the form width and clears a selection", async ({ page }) => {
    support.fileInputs = true;
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID);
    await runs.openInputReview();
    await runs.selectFile("Reporting period", "pipeline.csv");
    const attachment = page.locator('[data-slot="attachment"]');
    await expect(attachment).toContainText("Selected input");
    const card = await attachment.boundingBox();
    const form = await page.locator("form").boundingBox();
    expect(card!.width).toBeGreaterThan(form!.width * 0.8);
    await expect(page.getByLabel("Upload file for Reporting period")).not.toBeVisible();
    await page.getByRole("button", { name: "Remove pipeline.csv", exact: true }).click();
    await expect(attachment).toHaveCount(0);
    await runs.start();
    await expect(page.getByText("Reporting period is required", { exact: true })).toBeVisible();
    expect(support.starts).toHaveLength(0);
  });

  test("upload action opens the chooser and displays a removable attachment on mobile", async ({ page }) => {
    support.fileInputs = true;
    await page.setViewportSize({ width: 390, height: 844 });
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID);
    await runs.openInputReview();
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Upload file", exact: true }).click();
    await (await chooser).setFiles({ name: "uploaded.csv", mimeType: "text/csv", buffer: Buffer.from("product,quantity\napples,3\n") });
    await expect(page.getByRole("button", { name: "Remove uploaded.csv", exact: true })).toBeVisible();
    const attachment = await page.locator('[data-slot="attachment"]').boundingBox();
    expect(attachment!.x + attachment!.width).toBeLessThanOrEqual(390);
    await runs.start();
    await expect(page.getByLabel("Run detail")).toBeVisible();
    expect(support.starts).toHaveLength(1);
  });

  test("uploads actual input bytes before starting", async ({ page }) => {
    support.fileInputs = true;
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID);
    await runs.openInputReview();
    const bytes = Buffer.from("product,quantity\napples,3\n");
    await runs.uploadFile("Reporting period", bytes);
    await expect(page.getByRole("button", { name: "Remove uploaded.csv", exact: true })).toBeVisible();
    expect(support.uploadedBytes).toEqual(bytes);
    await runs.start();
    await expect(page.getByLabel("Run detail")).toBeVisible();
    expect(support.starts[0]).toMatchObject({ inputs: { period: { artifact_id: artifactFixture.id, checksum: support.uploaded.checksum } } });
  });

  test("failed upload preserves the prior selection", async ({ page }) => {
    support.fileInputs = true;
    support.failUpload = true;
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID);
    await runs.openInputReview();
    await runs.selectFile("Reporting period", "pipeline.csv");
    await runs.uploadFile("Reporting period", Buffer.from("failed upload"));
    await expect(page.getByText("Storage unavailable", { exact: true })).toBeVisible();
    await runs.start();
    await expect(page.getByLabel("Run detail")).toBeVisible();
    expect(support.starts[0]).toMatchObject({ inputs: { period: { checksum: artifactFixture.checksum } } });
  });

  test("presents final outputs and the selected step's file handoff", async ({ page }) => {
    support.fileInputs = true;
    support.state = "SUCCEEDED";
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID, true);
    await expect(page.getByLabel("Final outputs", { exact: true })).toContainText("pipeline.csv");
    await expect(page.getByLabel("Final outputs", { exact: true }).getByRole("img", { name: "Spreadsheet file" })).toBeVisible();
    await expect(page.getByLabel("Run artifacts", { exact: true })).toHaveCount(0);
    await expect(page.getByText("SHA-256:", { exact: false })).toHaveCount(0);
    await runs.selectStep("Step 2: Prepare summary");
    await expect(page.getByLabel("Step input files")).toContainText("pipeline.csv");
    await expect(page.getByLabel("Step outputs")).toContainText("pipeline.csv");
    await expect(page.getByLabel("Final outputs", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("Step artifacts", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("Step outputs").getByRole("button", { name: "Download pipeline.csv" })).toHaveCount(1);
    const all = page.getByRole("button", { name: "All artifacts", exact: true });
    const rail = await page.getByLabel("Step progress").boundingBox();
    const navigation = await all.boundingBox();
    expect(navigation!.y).toBeGreaterThan(rail!.y + rail!.height);
    await runs.showArtifacts();
    await expect(all).toHaveAttribute("aria-current", "page");
    await expect(page.getByRole("button", { name: "Result ready", exact: true })).not.toHaveAttribute("aria-current", "page");
    await expect(page.getByLabel("Run artifacts", { exact: true })).toContainText("pipeline.csv");
    await expect(page.getByLabel("Step outputs")).toHaveCount(0);
    await runs.showSummary();
    await expect(page.getByLabel("Final outputs", { exact: true })).toBeVisible();
  });

  for (const fileInputs of [false, true]) {
    test(`selected-view connector meets the grouped panel with ${fileInputs ? "files" : "empty file sections and a long rail"}`, async ({ page }) => {
      support.fileInputs = fileInputs;
      support.state = "SUCCEEDED";
      if (!fileInputs) support.stepStates = Array(5).fill("COMPLETED");
      const runs = new WorkflowRunsPage(page);
      await runs.goto(MOCK_AGENT_ID, true);
      const panel = page.getByLabel("Selected run view", { exact: true });
      await expect(panel).toHaveCSS("border-left-width", "1px");
      for (const view of ["summary", "step", "artifacts"]) {
        if (view === "summary") await runs.showSummary();
        else if (view === "step") await runs.selectStep(fileInputs ? "Step 2: Prepare summary" : "Step 5: Post summary");
        else await runs.showArtifacts();
        const geometry = await runs.selectedViewGeometry();
        expect(geometry.panel).not.toBeNull();
        expect(geometry.connector).not.toBeNull();
        const endpointX = geometry.connector!.x + geometry.connector!.width;
        const endpointY = geometry.connector!.y + geometry.connector!.height / 2;
        expect(Math.abs(endpointX - geometry.panel!.x)).toBeLessThan(2);
        expect(endpointY).toBeGreaterThan(geometry.panel!.y);
        expect(endpointY).toBeLessThan(geometry.panel!.y + geometry.panel!.height);
      }
      await page.setViewportSize({ width: 390, height: 844 });
      await expect(page.getByTestId("run-view-connector")).not.toBeVisible();
      const mobilePanel = await panel.boundingBox();
      expect(mobilePanel!.x + mobilePanel!.width).toBeLessThanOrEqual(390);
    });
  }

  test("explicit inputs start the pinned version and show actual run progress", async ({
    page,
  }) => {
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID);
    await runs.reviewInputs("This week");
    expect(support.starts).toHaveLength(0);
    await runs.start();
    await expect(
      page.getByRole("region", { name: "Run detail" }),
    ).toBeVisible();
    expect(support.starts[0]).toMatchObject({
      workflow_id: WORKFLOW_ID,
      agent_id: MOCK_AGENT_ID,
      version_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
      inputs: { period: "This week" },
    });
    expect(support.starts[0]).not.toHaveProperty("title");
    await expect(page.getByLabel("Step progress")).toBeVisible();
    await expect(page.getByLabel("Run timing")).toContainText("Time taken");
  });
  test("run detail returns to the Workflows page's Runs tab", async ({ page }) => {
    const runs = new WorkflowRunsPage(page);
    await runs.gotoOrganizationRun();
    await expect(page.getByLabel("Run detail")).toBeVisible();
    const navigation = page.getByRole("navigation", { name: "Workflow navigation" });
    await expect(navigation).toContainText("Run detail");
    await runs.backToRuns();
    await expect(page.getByRole("tab", { name: "Runs", selected: true })).toBeVisible();
    await expect(runs.runs("Active")).toBeVisible();
    await expect(page.getByLabel("Run detail")).not.toBeVisible();
    await expect(page).not.toHaveURL(/workflowRun=/);
    await page.reload();
    await expect(page.getByRole("tab", { name: "Runs", selected: true })).toBeVisible();
    await page.goBack();
    await expect(page.getByLabel("Run detail")).toBeVisible();
    await page.goForward();
    await expect(runs.runs("Active")).toBeVisible();
  });

  test("a run opened on its Agent's page returns to that Agent's runs", async ({ page }) => {
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID, true);
    await expect(page.getByLabel("Run detail")).toBeVisible();
    await runs.backToRuns();
    await expect(runs.runs("Recent runs")).toBeVisible();
    await expect(page).not.toHaveURL(/workflowRun=/);
  });

  test("a saved workflow lists its own runs", async ({ page }) => {
    const runs = new WorkflowRunsPage(page);
    await runs.gotoView("runs");
    await expect(page.getByRole("tab", { name: "Runs", selected: true })).toBeVisible();
    await expect(runs.runs("Runs of this workflow")).toContainText("Weekly pipeline report");
    expect(support.listQueries.at(-1)).toContain(`workflow_id=${WORKFLOW_ID}`);
  });

  for (const state of ["PAUSED", "BLOCKED"]) {
    for (const detail of [false, true]) {
      test(`${state} runs stop polling in ${detail ? "detail" : "list"} view`, async ({ page }) => {
        await page.clock.install();
        support.state = state;
        const runs = new WorkflowRunsPage(page);
        if (detail) await runs.goto(MOCK_AGENT_ID, true);
        else await runs.gotoAgentRuns(MOCK_AGENT_ID);
        await expect(page.getByLabel(detail ? "Run detail" : "Recent runs", { exact: true })).toBeVisible();
        const reads = support.reads;
        await page.clock.runFor(10_000);
        expect(support.reads).toBe(reads);
      });
    }
  }

  test("blocked runs explain how to proceed", async ({ page }) => {
    support.state = "BLOCKED";
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
    const summary = page.getByLabel("Run summary");
    await expect(summary.getByText("What to do next")).toBeVisible();
    await expect(summary.getByText(/step will not resume automatically/)).toBeVisible();
    await expect(summary.getByText(/Starting again may repeat actions/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Cancel run" })).toBeVisible();
  });

  const approvalRequest = (state: "LIVE" | "PARKED") => ({
    id: "00000000-0000-4000-8000-0000000000c1",
    step_index: 0,
    command: "rm -rf ./out && ./deploy.sh --prod",
    state,
    created_at: "2026-10-17T10:01:00Z",
    live_until: "2026-10-17T10:05:30Z",
    decided_by_user_id: null,
    decided_at: null,
    guidance: null,
  });

  test("a live approval leads the run page and records Approve once", async ({ page }) => {
    support.approval = approvalRequest("LIVE");
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
    await expect(page.getByRole("status").getByText("Waiting on you")).toBeVisible();
    await expect(page.getByLabel("Step progress").getByText("Waiting on you")).toBeVisible();
    const gate = page.getByLabel("Approval required");
    await expect(gate.getByRole("heading")).toHaveText(/to run this command\?/);
    await expect(gate.getByText("rm -rf ./out && ./deploy.sh --prod")).toBeVisible();
    await expect(gate.getByRole("timer")).toBeVisible();
    const request = page.getByLabel("Run activity").locator("li").first();
    await expect(request.locator("code")).toHaveText("rm -rf ./out && ./deploy.sh --prod");
    await expect(request).toContainText("Approval requested to run");
    await expect(request).toContainText("approval_requested");
    await gate.getByRole("button", { name: "Approve once" }).click();
    await expect(gate).toHaveCount(0);
    expect(support.decisions).toEqual([{ decision: "approve" }]);
  });

  test("a paused run is declined with verbatim guidance and continues", async ({ page }) => {
    support.state = "AWAITING_APPROVAL";
    support.approval = approvalRequest("PARKED");
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
    await expect(page.getByRole("status").getByText("Awaiting approval · paused")).toBeVisible();
    const gate = page.getByLabel("Approval required");
    await expect(gate.getByText(/resumes the same session/)).toBeVisible();
    await gate.getByRole("textbox").fill("Write to ./tmp instead, never ./out");
    await gate.getByRole("button", { name: "Decline & continue" }).click();
    await expect(page.getByLabel("Run summary").getByRole("heading")).toHaveText("Waiting to start");
    expect(support.decisions).toEqual([{ decision: "decline", guidance: "Write to ./tmp instead, never ./out" }]);
  });

  test("Viewers see the requested command but cannot decide", async ({ page }) => {
    support.viewer = true;
    support.approval = approvalRequest("LIVE");
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
    const gate = page.getByLabel("Approval required");
    await expect(gate.getByText("rm -rf ./out && ./deploy.sh --prod")).toBeVisible();
    await expect(gate.getByRole("button")).toHaveCount(0);
    await expect(gate.getByText(/Ask someone with permission/)).toBeVisible();
  });

  test("decided commands stay on their step with who decided and the guidance", async ({ page }) => {
    support.approvals = [
      { ...approvalRequest("LIVE"), id: "00000000-0000-4000-8000-0000000000c2", command: "mkdir -p /tmp/af390", state: "RELEASED", decided_by_user_id: null, decided_at: "2026-10-17T10:01:30Z" },
      { ...approvalRequest("LIVE"), state: "DECLINED", decided_at: "2026-10-17T10:02:00Z", guidance: "List the folder instead" },
    ];
    const runs = new WorkflowRunsPage(page);
    support.stepStates = ["RUNNING", "PENDING"];
    await runs.goto(MOCK_AGENT_ID, true);
    const rail = page.getByLabel("Step progress");
    await expect(rail.getByText("1 approved")).toBeVisible();
    await expect(rail.getByText("1 declined")).toBeVisible();
    await runs.selectStep("Step 1: Read pipeline");
    const history = page.getByLabel("Approvals in step 1");
    await expect(history.getByText("Approved and sent to the Agent")).toBeVisible();
    await expect(history.getByText("Declined · never run")).toBeVisible();
    await expect(history.getByText("“List the folder instead”")).toBeVisible();
  });

  test("the Workflows page lists runs waiting on approval and opens one", async ({ page }) => {
    support.state = "AWAITING_APPROVAL";
    support.approval = approvalRequest("PARKED");
    await page.goto(`/dashboard/${TEST_ORG_ID}/agents/${MOCK_AGENT_ID}?tab=workflows`);
    const inbox = page.getByLabel("Waiting on your approval");
    await expect(inbox.getByText("rm -rf ./out && ./deploy.sh --prod")).toBeVisible();
    await expect(inbox.getByText(/^Paused · /)).toBeVisible();
    // The Agent's Workflows section and the Organization's Workflows page both count it.
    await expect(page.getByRole("complementary").getByLabel("1 waiting on you")).toBeVisible();
    await inbox.getByRole("button", { name: "Review →" }).click();
    await expect(page.getByLabel("Approval required")).toBeVisible();
  });

  test("an approval the viewer cannot decide is listed without counting as waiting on them", async ({
    page,
  }) => {
    support.viewer = true;
    support.state = "AWAITING_APPROVAL";
    support.approval = approvalRequest("PARKED");
    const runs = new WorkflowRunsPage(page);
    await runs.gotoLanding();
    await expect(
      page.getByLabel("Waiting on approval").getByText("rm -rf ./out && ./deploy.sh --prod"),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: /Workflows/ }).getByLabel(/waiting on you/),
    ).toHaveCount(0);
  });

  test("the Organization's Workflows page lists approvals across Agents with their Agent", async ({ page }) => {
    support.state = "AWAITING_APPROVAL";
    support.approval = approvalRequest("PARKED");
    const runs = new WorkflowRunsPage(page);
    await runs.gotoLanding();
    const inbox = page.getByLabel("Waiting on your approval");
    await expect(inbox.getByText("rm -rf ./out && ./deploy.sh --prod")).toBeVisible();
    await expect(inbox).toContainText("Maya");
    await expect(
      page.getByRole("link", { name: /Workflows/ }).getByLabel("1 waiting on you"),
    ).toBeVisible();
    await inbox.getByRole("button", { name: "Review →" }).click();
    await expect(page.getByLabel("Approval required")).toBeVisible();
  });

  test("the Workflows page opens on runs, keeps New workflow and lists saved workflows", async ({ page }) => {
    support.state = "SUCCEEDED";
    const runs = new WorkflowRunsPage(page);
    await runs.gotoLanding();
    await expect(page.getByRole("button", { name: "New workflow" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Runs", selected: true })).toBeVisible();
    const recent = runs.runs("Recent");
    await expect(recent.getByText("Completed")).toBeVisible();
    await expect(runs.runs("Active")).toHaveCount(0);
    await expect(page.getByLabel("Waiting on your approval")).toHaveCount(0);
    await page.getByRole("tab", { name: "Workflows" }).click();
    await expect(page.getByLabel("Saved workflows")).toBeVisible();
    await expect(page).toHaveURL(/workflowsTab=workflows/);
    await page.getByRole("tab", { name: "Runs" }).click();
    await recent.getByRole("button").first().click();
    await expect(page.getByLabel("Run detail")).toBeVisible();
  });

  test("running detail keeps polling and displays completion", async ({ page }) => {
    await page.clock.install();
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
    await expect(page.getByLabel("Run detail")).toBeVisible();
    support.state = "SUCCEEDED";
    await page.clock.runFor(3_100);
    await expect(page.getByLabel("Run summary").getByRole("heading")).toHaveText("Run completed");
  });

  test("workflow tabs persist in the URL, reload and browser history", async ({
    page,
  }) => {
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID);
    for (const [label, value] of [
      ["Version history", "history"],
      ["Overview", "overview"],
    ] as const) {
      await runs.selectView(label);
      await expect(page).toHaveURL(new RegExp(`workflowView=${value}`));
      await page.reload();
      await expect(
        page.getByRole("tab", { name: label, exact: true }),
      ).toHaveAttribute("aria-selected", "true");
    }
    await page.goBack();
    await expect(
      page.getByRole("tab", { name: "Version history", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    await page.goForward();
    await expect(
      page.getByRole("tab", { name: "Overview", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
  });

  test("opening a run from Recent runs and returning keeps the Runs tab", async ({
    page,
  }) => {
    const runs = new WorkflowRunsPage(page);
    await runs.gotoLanding();
    await runs.openFirstRun("Active");
    await expect(page.getByLabel("Run detail")).toBeVisible();
    await runs.backToRuns();
    await expect(page.getByRole("heading", { name: "Workflows", exact: true })).toBeVisible();
    await expect(runs.runs("Active")).toBeVisible();
    expect(new URL(page.url()).searchParams.get("workflow")).toBeNull();
  });

  test("an invalid workflow view falls back to Overview", async ({ page }) => {
    await new WorkflowRunsPage(page).gotoView("unknown");
    await expect(
      page.getByRole("tab", { name: "Overview", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
  });

  test("run timing replaces activity with real step and total durations", async ({
    page,
  }) => {
    support.state = "SUCCEEDED";
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID, true);
    const timing = page.getByLabel("Run timing");
    await expect(timing).toContainText("Total 2m 18s");
    await expect(timing.locator("dd")).toHaveText(["1m 54s", "24s"]);
    await expect(page.getByLabel("Run history")).toHaveCount(0);
    await runs.selectStep("Step 1: Read pipeline");
    await expect(page.getByLabel("Step detail")).toContainText(
      "Completed in 1m 54s",
    );
  });

  test("a running step shows its attempt and activity", async ({
    page,
  }) => {
    support.runReason = "Pipedrive is not connected";
    support.attempt = {
      number: 2,
      started_at: "2026-10-17T10:01:00Z",
      expires_at: "2026-10-17T10:16:00Z",
      server_time: "2026-10-17T10:02:00Z",
      agent_unresponsive: false,
    };
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
    const summary = page.getByLabel("Run summary");
    await expect(summary).toContainText("Attempt 2");
    await expect(summary).toContainText("Pipedrive is not connected");
    const activity = page.getByLabel("Run activity");
    await expect(activity.locator("li")).toHaveText([
      /Pipedrive is not connected/,
      /Run started using version 1/,
    ]);
  });

  test("activity picks up the final transition after the run settles", async ({
    page,
  }) => {
    await page.clock.install();
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
    const activity = page.getByLabel("Run activity");
    await expect(activity).not.toContainText("Step completed");
    support.state = "SUCCEEDED";
    await page.clock.runFor(3_100);
    await expect(activity.locator("li").first()).toHaveText(
      /^\d\d:\d\dStep completed/,
    );
    await expect(activity).not.toContainText("## Final step");
  });

  test("an activity load failure is shown inline and can be retried", async ({
    page,
  }) => {
    support.failHistory = true;
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
    await expect(page.getByText("Couldn’t load run activity")).toBeVisible();
    support.failHistory = false;
    await page
      .getByText("Couldn’t load run activity")
      .locator("xpath=ancestor::*[.//button][1]")
      .getByRole("button", { name: "Try again" })
      .click();
    await expect(page.getByLabel("Run activity")).toBeVisible();
  });

  test("an Agent that has not accepted the step is called out", async ({
    page,
  }) => {
    support.attempt = {
      number: 1,
      started_at: "2026-10-17T10:00:00Z",
      expires_at: "2026-10-17T10:15:00Z",
      server_time: "2026-10-17T10:02:00Z",
      agent_unresponsive: true,
    };
    support.runReason = "Pipedrive is not connected";
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
    const summary = page.getByLabel("Run summary");
    await expect(summary.getByRole("alert")).toContainText("hasn’t accepted");
    // The unresponsive warning must not hide why the previous attempt failed.
    await expect(summary).toContainText("Pipedrive is not connected");
  });

  test("attempt times follow the API's clock, not the browser's", async ({
    page,
  }) => {
    support.attempt = {
      number: 1,
      started_at: "2026-10-17T10:00:00Z",
      expires_at: "2026-10-17T10:15:00Z",
      server_time: "2026-10-17T10:05:00Z",
      agent_unresponsive: false,
    };
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
    await expect(page.getByLabel("Run summary")).toContainText(
      /running 5m \d+s · times out in (10m 0s|9m \d+s)/,
    );
  });

  test("unfinished steps show their status instead of fabricated durations", async ({
    page,
  }) => {
    support.stepStates = ["COMPLETED", "RUNNING", "PENDING"];
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
    await expect(page.getByLabel("Run timing").locator("dd")).toHaveText([
      "1m 54s",
      "In progress",
      "Not started",
    ]);
  });

  test("step connector joins the centers and edges of adjacent markers", async ({
    page,
  }) => {
    support.state = "SUCCEEDED";
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID, true);
    await expect(page.getByLabel("Step progress")).toBeVisible();
    const { first, second, connector } = await runs.stepConnectorGeometry();
    expect(first).not.toBeNull();
    expect(second).not.toBeNull();
    expect(connector).not.toBeNull();
    expect(
      Math.abs(
        connector!.x + connector!.width / 2 - (first!.x + first!.width / 2),
      ),
    ).toBeLessThan(1);
    expect(
      Math.abs(
        connector!.x + connector!.width / 2 - (second!.x + second!.width / 2),
      ),
    ).toBeLessThan(1);
    expect(Math.abs(connector!.y - (first!.y + first!.height))).toBeLessThan(1);
    expect(Math.abs(connector!.y + connector!.height - second!.y)).toBeLessThan(
      1,
    );
  });

  test("cancel is explicit and preserves completed step summaries", async ({
    page,
  }) => {
    const runs = new WorkflowRunsPage(page);
    support.stepStates = ["COMPLETED", "RUNNING"];
    await runs.goto(MOCK_AGENT_ID, true);
    await runs.cancel();
    await expect(page.getByLabel("Run detail")).toContainText("Cancelled");
    await runs.selectStep("Step 1: Read pipeline");
    await expect(page.getByLabel("Step detail")).toContainText(
      "Finished read pipeline.",
    );
  });

  test("completed run shows the model's final summary and no redundant back button", async ({
    page,
  }) => {
    support.state = "SUCCEEDED";
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
    const summary = page.getByLabel("Run summary");
    await expect(summary.getByRole("heading")).toHaveText("Run completed");
    await expect(summary).toContainText(`Summary from ${mockAgent.name}`);
    await expect(summary.locator("strong")).toHaveText(
      "weekly pipeline report",
    );
    await expect(page.getByLabel("Output files")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Download", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Back to workflow" }),
    ).toHaveCount(0);
  });
  test("selecting a step replaces the panel and can return to the run overview", async ({
    page,
  }) => {
    support.stepStates = ["COMPLETED", "COMPLETED", "RUNNING", "PENDING"];
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID, true);
    await expect(page.getByLabel("Run summary")).toBeVisible();
    await runs.selectStep("Step 1: Read pipeline");
    const panel = page.getByLabel("Step detail");
    await expect(panel).toContainText("Finished read pipeline.");
    await expect(page.getByLabel("Run summary")).toHaveCount(0);
    await expect(
      page
        .getByLabel("Step progress")
        .getByRole("button", { name: "Step 1: Read pipeline", exact: true }),
    ).toHaveAttribute("aria-current", "step");
    await runs.selectStep("Step 2: Score and segment");
    await expect(panel).toContainText("Finished score and segment.");
    await expect(panel).not.toContainText("Finished read pipeline.");
    await runs.selectStep("Step 3: Prepare summary");
    await expect(panel).toContainText("This step is in progress.");
    await runs.selectStep("Step 4: Review results");
    await expect(panel).toContainText("Waiting for earlier work to finish.");
    await runs.showSummary();
    await expect(page.getByLabel("Run summary")).toBeVisible();
    await expect(panel).toHaveCount(0);
  });

  test("Result ready card opens the final summary after inspecting any completed step", async ({
    page,
  }) => {
    support.state = "SUCCEEDED";
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID, true);
    const result = page.getByRole("button", {
      name: "Result ready",
      exact: true,
    });
    await expect(result).toHaveAttribute("aria-current", "page");
    await expect(result).toContainText("View final summary");
    await expect(page.getByLabel("Run summary")).toContainText(
      "weekly pipeline report",
    );
    await runs.selectStep("Step 1: Read pipeline");
    await expect(result).not.toHaveAttribute("aria-current", "page");
    await expect(page.getByLabel("Step detail")).toContainText(
      "Finished read pipeline.",
    );
    await runs.selectStep("Step 2: Prepare summary");
    await expect(page.getByLabel("Step detail")).toContainText(
      "Finished prepare summary.",
    );
    await runs.showSummary();
    await expect(result).toHaveAttribute("aria-current", "page");
    await expect(page.getByLabel("Run summary").locator("strong")).toHaveText(
      "weekly pipeline report",
    );
    await expect(page.getByLabel("Step detail")).toHaveCount(0);
  });

  test("failed start retains inputs and reuses its request identity", async ({
    page,
  }) => {
    support.failStart = true;
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID);
    await runs.reviewInputs("This week");
    await runs.start();
    await expect(
      page.getByText(
        "The run could not be started. Your inputs are retained.",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(page.getByLabel("Reporting period (required)")).toHaveValue(
      "This week",
    );
    await runs.start();
    await expect(page.getByLabel("Run detail")).toBeVisible();
    expect(support.starts[0].client_request_id).toBe(
      support.starts[1].client_request_id,
    );
  });
  for (const state of ["FAILED", "CANCELLED", "SUCCEEDED"]) {
    test(`${state} runs offer Run again`, async ({ page }) => {
      support.state = state;
      await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
      await expect(
        page.getByRole("button", { name: "Run again", exact: true }),
      ).toBeVisible();
    });
  }
  for (const state of ["QUEUED", "RUNNING", "PAUSED", "BLOCKED"]) {
    test(`${state} runs do not offer Run again`, async ({ page }) => {
      support.state = state;
      await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
      await expect(page.getByLabel("Run detail")).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Run again", exact: true }),
      ).toHaveCount(0);
    });
  }
  test("Run again asks first, then starts a marked re-run that sends no inputs", async ({
    page,
  }) => {
    support.state = "FAILED";
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID, true);
    await runs.runAgain();
    await expect(page.getByRole("dialog")).toContainText(
      "same inputs as this one",
    );
    expect(support.reruns).toHaveLength(0);
    await runs.confirmRunAgain();
    await expect(page).toHaveURL(new RegExp(`workflowRun=${RERUN_ID}`));
    await expect(page.getByLabel("Run detail")).toContainText("Re-run of");
    await expect(page.getByLabel("Run activity").locator("li")).toHaveText([
      /Re-run of run 12345678 using version 1/,
    ]);
    expect(Object.keys(support.reruns[0])).toEqual(["client_request_id"]);
    expect(support.starts).toHaveLength(0);
    await page.getByRole("button", { name: /^run 12345678$/ }).click();
    await expect(page).toHaveURL(new RegExp(`workflowRun=${RUN_ID}`));
    await expect(page.getByLabel("Run summary")).toContainText("Run failed");
    await runs.backToRuns();
    await expect(
      page.getByLabel("Recent runs", { exact: true }),
    ).toContainText("· Re-run");
  });
  test("a re-run can be declined and a dropped request retries with the same identity", async ({
    page,
  }) => {
    support.state = "SUCCEEDED";
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID, true);
    await runs.runAgain();
    await page.getByRole("button", { name: "Not now" }).click();
    await expect(page.locator('[data-slot="dialog-content"]')).toHaveCount(0);
    expect(support.reruns).toHaveLength(0);
    support.failRerun = true;
    await runs.runAgain();
    expect(support.reruns).toHaveLength(0);
    await runs.confirmRunAgain();
    await expect(
      page.getByText("This run could not be run again"),
    ).toBeVisible();
    await expect(page.locator('[data-slot="dialog-content"]')).toHaveCount(0);
    await runs.runAgain();
    await runs.confirmRunAgain();
    await expect(page).toHaveURL(new RegExp(`workflowRun=${RERUN_ID}`));
    expect(support.reruns[0].client_request_id).toBe(
      support.reruns[1].client_request_id,
    );
  });
  test("losing access during a re-run replaces the protected run content", async ({
    page,
  }) => {
    support.state = "SUCCEEDED";
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID, true);
    await expect(page.getByLabel("Run summary")).toBeVisible();
    await runs.runAgain();
    support.failRead = true;
    await runs.confirmRunAgain();
    await expect(
      page.getByText("This run is unavailable", { exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel("Run summary")).toHaveCount(0);
  });
  test("Viewers cannot run a settled run again", async ({ page }) => {
    support.viewer = true;
    support.state = "FAILED";
    await new DataSupport(page).agents.interceptGetAgentRequest({
      body: { ...mockAgent, allowed_actions: ["agent.read"] },
    });
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
    await expect(page.getByLabel("Run detail")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Run again", exact: true }),
    ).toHaveCount(0);
  });

  test("Viewer inspects text results without start or cancel authority", async ({
    page,
  }) => {
    support.viewer = true;
    support.state = "SUCCEEDED";
    const viewerAgent = { ...mockAgent, allowed_actions: ["agent.read"] };
    const data = new DataSupport(page);
    await data.agents.interceptGetAgentRequest({ body: viewerAgent });
    await data.agents.interceptGetAgentsRequest({
      body: { page: 1, page_size: 50, total: 1, items: [viewerAgent] },
    });
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID);
    // Any Member may open the dialog; starting needs an Agent they can update.
    await runs.openRunDialog();
    await expect(runs.dialog()).toContainText("No running agent you can update");
    await expect(runs.runAs("Maya")).toHaveCount(0);
    await expect(
      runs.dialog().getByRole("button", { name: "Start run", exact: true }),
    ).toBeDisabled();
    await runs.goto(MOCK_AGENT_ID, true);
    await expect(page.getByLabel("Run summary")).toContainText(
      "weekly pipeline report",
    );
    await expect(
      page.getByRole("button", { name: "Cancel run", exact: true }),
    ).toHaveCount(0);
  });
  test("revoked access conceals the run and text results", async ({ page }) => {
    support.failRead = true;
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true, TEST_ORG_ID);
    await expect(
      page.getByText("This run is unavailable", { exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel("Run summary")).toHaveCount(0);
  });
  test("Organization switching cannot reuse cached text results", async ({
    page,
  }) => {
    const otherId = "99999999-9999-4999-8999-999999999999";
    await new WorkflowDataSupport(page).enableOrganizationSwitch(otherId);
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID, true);
    await expect(page.getByLabel("Run summary")).toBeVisible();
    await new WorkflowsPage(page).switchOrganization("Globex");
    await expect(page).toHaveURL(new RegExp(otherId));
    await expect(page.getByLabel("Step detail")).toHaveCount(0);
    await runs.goto(MOCK_AGENT_ID, true, otherId);
    await expect(
      page.getByText("This run is unavailable", { exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel("Run summary")).toHaveCount(0);
    await expect(page.getByLabel("Run history")).toHaveCount(0);
  });
  const OTHER_AGENT_ID = "77777777-7777-4777-8777-777777777777";
  const twoAgents = async (page: import("@playwright/test").Page) =>
    new DataSupport(page).agents.interceptGetAgentsRequest({
      body: {
        page: 1,
        page_size: 50,
        total: 2,
        items: [mockAgent, { ...mockAgent, id: OTHER_AGENT_ID, name: "Rex" }],
      },
    });

  test("the Run dialog preselects the workflow's default Agent and runs as the one chosen", async ({
    page,
  }) => {
    await twoAgents(page);
    support.defaultAgentId = OTHER_AGENT_ID;
    await support.intercept(MOCK_AGENT_ID);
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID);
    await runs.openRunDialog();
    await expect(runs.runAs("Rex")).toBeChecked();
    await expect(runs.runAs("Maya")).not.toBeChecked();
    await runs.chooseAgent("Maya");
    await runs.dialog().getByLabel("Name this run").fill("Week 42 report");
    await page.getByLabel("Reporting period (required)").fill("Week 42");
    await runs.start();
    await expect(page.getByLabel("Run detail")).toBeVisible();
    expect(support.starts[0]).toMatchObject({
      agent_id: MOCK_AGENT_ID,
      title: "Week 42 report",
    });
    await expect(page.getByRole("heading", { name: "Week 42 report" })).toBeVisible();
  });

  test("Run as shows four Agents and the default, with the rest behind a search", async ({
    page,
  }) => {
    const team = Array.from({ length: 8 }, (_, i) => ({
      ...mockAgent,
      id: i === 0 ? MOCK_AGENT_ID : `00000000-0000-4000-8000-0000000001${String(i + 10)}`,
      name: i === 0 ? "Maya" : `Agent ${String.fromCharCode(65 + i)}`,
    }));
    await new DataSupport(page).agents.interceptGetAgentsRequest({
      body: { page: 1, page_size: 50, total: team.length, items: team },
    });
    // The default is past the first four, so it gets a pill of its own.
    support.defaultAgentId = team[5].id;
    await support.intercept(MOCK_AGENT_ID);
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID);
    await runs.openRunDialog();
    await expect(runs.runAs(team[5].name)).toBeChecked();
    await expect(runs.dialog().getByRole("radio")).toHaveCount(5);
    await expect(runs.runAs(team[6].name)).toHaveCount(0);
    await runs.dialog().getByRole("button", { name: "Choose from all 8 agents" }).click();
    await page.getByPlaceholder("Search agents…").fill(team[6].name);
    await page.getByRole("option", { name: team[6].name }).click();
    await expect(runs.runAs(team[6].name)).toBeChecked();
    await page.getByLabel("Reporting period (required)").fill("Week 42");
    await runs.start();
    await expect(page.getByLabel("Run detail")).toBeVisible();
    expect(support.starts[0]).toMatchObject({ agent_id: team[6].id });
  });

  test("a link from an Agent's page preselects that Agent over the default", async ({ page }) => {
    await twoAgents(page);
    support.defaultAgentId = OTHER_AGENT_ID;
    await support.intercept(MOCK_AGENT_ID);
    const runs = new WorkflowRunsPage(page);
    await runs.gotoAgentRuns(MOCK_AGENT_ID);
    await page.getByRole("link", { name: "Run a workflow" }).click();
    await expect(page).toHaveURL(new RegExp(`/workflows\\?.*agent=${MOCK_AGENT_ID}`));
    await page.getByRole("button", { name: "Run Weekly pipeline report" }).click();
    await expect(runs.runAs("Maya")).toBeChecked();
    // The link named the Agent for this run only: once it starts, the default returns.
    await page.getByLabel("Reporting period (required)").fill("Week 42");
    await runs.start();
    await expect(page.getByLabel("Run detail")).toBeVisible();
    await expect(page).not.toHaveURL(/agent=/);
  });

  test("with no default the dialog waits for an Agent, and files follow the Agent chosen", async ({
    page,
  }) => {
    await twoAgents(page);
    support.fileInputs = true;
    await support.intercept(OTHER_AGENT_ID);
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID);
    await runs.openRunDialog();
    await expect(runs.dialog()).toContainText("Choose an agent under “Run as”");
    await expect(
      runs.dialog().getByRole("button", { name: "Start run", exact: true }),
    ).toBeDisabled();
    await runs.chooseAgent("Maya");
    await runs.selectFile("Reporting period", "pipeline.csv");
    await expect(runs.dialog()).toContainText("pipeline.csv");
    // Another Agent has other files, so the earlier pick is dropped.
    await runs.chooseAgent("Rex");
    await expect(
      page.getByRole("combobox", { name: "Select file for Reporting period" }),
    ).not.toContainText("pipeline.csv");
    // The dropped file is gone from the run too, not only from the picker.
    await runs.start();
    await expect(runs.dialog().getByRole("alert")).toContainText("Reporting period is required");
    expect(support.starts).toHaveLength(0);
  });

  test("the Agent cannot change while a file uploads", async ({ page }) => {
    await twoAgents(page);
    support.fileInputs = true;
    await support.intercept(OTHER_AGENT_ID);
    let release = () => {};
    support.uploadGate = new Promise((resolve) => (release = resolve));
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID);
    await runs.openRunDialog();
    await runs.chooseAgent("Maya");
    await runs.uploadFile("Reporting period", Buffer.from("product,quantity\n"));
    await expect(runs.runAs("Rex")).toBeDisabled();
    release();
    await expect(page.getByRole("button", { name: "Remove uploaded.csv", exact: true })).toBeVisible();
    await expect(runs.runAs("Rex")).toBeEnabled();
  });

  test("a workflow's runs open on their first page, whatever page the landing list was on", async ({
    page,
  }) => {
    const runs = new WorkflowRunsPage(page);
    await runs.gotoLanding("?workflowsTab=workflows&workflowRunPage=3");
    await new WorkflowsPage(page).open("Weekly pipeline report");
    await expect(page).toHaveURL(new RegExp(`workflow=${WORKFLOW_ID}`));
    await expect(page).not.toHaveURL(/workflowRunPage/);
  });

  test("the Organization lists runs across Agents; an Agent's tab lists only its own", async ({
    page,
  }) => {
    support.state = "SUCCEEDED";
    support.otherAgentRun = { agent_id: OTHER_AGENT_ID, agent_name: "Rex" };
    const runs = new WorkflowRunsPage(page);
    await runs.gotoLanding();
    const recent = runs.runs("Recent");
    await expect(recent.getByRole("button")).toHaveCount(2);
    await expect(recent).toContainText("Maya");
    await expect(recent).toContainText("Rex");
    await runs.gotoAgentRuns(MOCK_AGENT_ID);
    await expect(runs.runs("Recent runs").getByRole("button")).toHaveCount(1);
    expect(support.listQueries.at(-1)).toContain(`agent_id=${MOCK_AGENT_ID}`);
    // Workflows are created for the Organization, not on an Agent's page.
    await expect(page.getByRole("button", { name: "New workflow" })).toHaveCount(0);
  });

  test("a run on a deleted Agent names it as archived, without a link to it", async ({ page }) => {
    support.state = "SUCCEEDED";
    support.agentArchived = true;
    support.viewer = true;
    const runs = new WorkflowRunsPage(page);
    await runs.gotoLanding();
    await expect(runs.runs("Recent")).toContainText("Archived");
    await runs.openFirstRun();
    const detail = page.getByLabel("Run detail");
    await expect(detail).toContainText("Archived");
    await expect(detail.getByRole("link", { name: /Open Maya/ })).toHaveCount(0);
    await expect(detail.getByRole("button", { name: "Run again" })).toHaveCount(0);
  });

  test("an old run still shows the output its step was asked for", async ({ page }) => {
    support.state = "SUCCEEDED";
    support.fileInputs = true;
    support.outputDescription = "A readable Markdown report";
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID, true);
    await runs.selectStep("Step 1: Read pipeline");
    await expect(page.getByLabel("Step outputs")).toContainText("A readable Markdown report");
  });
  test("Open latest run on a workflow card opens its newest run", async ({ page }) => {
    support.state = "SUCCEEDED";
    const workflows = new WorkflowsPage(page);
    await workflows.goto();
    await workflows.cardAction("Weekly pipeline report", "Open latest run");
    await expect(page.getByLabel("Run detail")).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`workflowRun=${RUN_ID}`));
    expect(support.listQueries.at(-1)).toContain(`workflow_id=${WORKFLOW_ID}`);
    expect(support.listQueries.at(-1)).toContain("page_size=1");
  });
});
