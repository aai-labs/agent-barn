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
    await new WorkflowDataSupport(page).intercept(MOCK_AGENT_ID, {
      saved: true,
    });
    support = new WorkflowRunDataSupport(page);
    await support.intercept(MOCK_AGENT_ID);
  });
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
      version_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
      inputs: { period: "This week" },
    });
    await expect(page.getByLabel("Step progress")).toBeVisible();
    await expect(page.getByLabel("Run timing")).toContainText("Time taken");
  });
  test("run detail returns to its workflow's Runs tab", async ({ page }) => {
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID, true);
    await expect(page.getByLabel("Run detail")).toBeVisible();
    const navigation = page.getByRole("navigation", {
      name: "Workflow navigation",
    });
    await expect(
      navigation.getByRole("button", { name: "Back to runs" }),
    ).toHaveText("Runs");
    await expect(
      page.getByRole("button", { name: "Back to runs" }),
    ).toHaveCount(1);
    await runs.backToRuns();
    await expect(
      page.getByRole("tab", { name: "Runs", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    await expect(
      page.getByLabel("Workflow runs", { exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel("Run detail")).not.toBeVisible();
    await expect(page).not.toHaveURL(/workflowRun=/);
    await expect(page).toHaveURL(/workflowView=runs/);
    expect(new URL(page.url()).searchParams.get("workflow")).toBe(WORKFLOW_ID);
    await expect(navigation).toContainText("Weekly pipeline report");
    await page.reload();
    await expect(
      page.getByRole("tab", { name: "Runs", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    await page.goBack();
    await expect(page.getByLabel("Run detail")).toBeVisible();
    await page.goForward();
    await expect(
      page.getByLabel("Workflow runs", { exact: true }),
    ).toBeVisible();
  });

  for (const state of ["PAUSED", "BLOCKED"]) {
    for (const detail of [false, true]) {
      test(`${state} runs stop polling in ${detail ? "detail" : "list"} view`, async ({ page }) => {
        await page.clock.install();
        support.state = state;
        const runs = new WorkflowRunsPage(page);
        if (detail) await runs.goto(MOCK_AGENT_ID, true);
        else await runs.gotoView(MOCK_AGENT_ID, "runs");
        await expect(page.getByLabel(detail ? "Run detail" : "Workflow runs", { exact: true })).toBeVisible();
        const reads = support.reads;
        await page.clock.runFor(10_000);
        expect(support.reads).toBe(reads);
      });
    }
  }

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
      ["Runs", "runs"],
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
    await page.goBack();
    await expect(
      page.getByRole("tab", { name: "Runs", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    await page.goForward();
    await expect(
      page.getByRole("tab", { name: "Version history", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
  });

  test("opening a run from Runs and returning keeps the same workflow context", async ({
    page,
  }) => {
    const runs = new WorkflowRunsPage(page);
    await runs.gotoView(MOCK_AGENT_ID, "runs");
    await runs.openFirstRun();
    await expect(page.getByLabel("Run detail")).toBeVisible();
    await runs.backToRuns();
    await expect(
      page.getByRole("heading", {
        name: "Weekly pipeline report",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByLabel("Workflow runs", { exact: true }),
    ).toBeVisible();
    expect(new URL(page.url()).searchParams.get("workflow")).toBe(WORKFLOW_ID);
    await expect(page).toHaveURL(/workflowView=runs/);
  });

  test("an invalid workflow view falls back to Overview", async ({ page }) => {
    await new WorkflowRunsPage(page).gotoView(MOCK_AGENT_ID, "unknown");
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

  test("a retrying step shows its attempt, the failure reason and the activity", async ({
    page,
  }) => {
    support.runReason = "Step failed, retrying: Pipedrive is not connected";
    support.attempt = {
      number: 2,
      limit: 3,
      started_at: "2026-10-17T10:01:00Z",
      expires_at: "2026-10-17T10:16:00Z",
      server_time: "2026-10-17T10:02:00Z",
      agent_unresponsive: false,
    };
    await new WorkflowRunsPage(page).goto(MOCK_AGENT_ID, true);
    const summary = page.getByLabel("Run summary");
    await expect(summary).toContainText("Attempt 2 of 3");
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
      /Step completed$/,
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
      limit: 3,
      started_at: "2026-10-17T10:00:00Z",
      expires_at: "2026-10-17T10:15:00Z",
      server_time: "2026-10-17T10:02:00Z",
      agent_unresponsive: true,
    };
    support.runReason = "Step failed, retrying: Pipedrive is not connected";
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
      limit: 3,
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
    await expect(panel).toContainText("This step has not started yet.");
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
      page.getByLabel("Workflow runs", { exact: true }),
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
    expect(support.reruns).toHaveLength(0);
    support.failRerun = true;
    await runs.runAgain();
    await runs.confirmRunAgain();
    await expect(
      page.getByText("This run could not be run again"),
    ).toBeVisible();
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
    await new DataSupport(page).agents.interceptGetAgentRequest({
      body: { ...mockAgent, allowed_actions: ["agent.read"] },
    });
    const runs = new WorkflowRunsPage(page);
    await runs.goto(MOCK_AGENT_ID);
    await expect(
      page.getByRole("button", { name: "Run workflow", exact: true }),
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
});
