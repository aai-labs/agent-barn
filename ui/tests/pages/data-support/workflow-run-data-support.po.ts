import { type Page } from "@playwright/test";
import { workflowFixture, WORKFLOW_ID } from "../../fixtures/workflows";
import { TEST_ORG_ID } from "../../constants";

export const RUN_ID = "12345678-1234-4234-8234-123456789abc";
export const RERUN_ID = "87654321-4321-4432-8432-cba987654321";
const stepTimes = [
  { started_at: "2026-10-17T10:00:00Z", completed_at: "2026-10-17T10:01:54Z" },
  { started_at: "2026-10-17T10:01:54Z", completed_at: "2026-10-17T10:02:18Z" },
];
export class WorkflowRunDataSupport {
  starts: Record<string, unknown>[] = [];
  reads = 0;
  failStart = false;
  /** The next re-run request fails in transport, as a dropped connection would. */
  failRerun = false;
  reruns: Record<string, unknown>[] = [];
  failRead = false;
  viewer = false;
  state = "RUNNING";
  attempt: Record<string, unknown> | null = null;
  runReason: string | null = null;
  /** Overrides the step list with this many-step progression (for walkthrough captures). */
  stepStates: string[] | null = null;
  constructor(private page: Page) {}
  async intercept(agentId: string) {
    const fixture = workflowFixture(agentId);
    const base = `**/api/v1/organizations/*/agents/${agentId}`;
    const run = (over: Record<string, unknown> = {}) => ({
      id: RUN_ID,
      workflow_id: WORKFLOW_ID,
      version_id: fixture.version.id,
      version_number: 1,
      name: fixture.version.draft.name,
      initiating_user_id: null,
      inputs: { period: "This week" },
      state: this.state,
      revision: this.state === "RUNNING" ? 2 : 3,
      next_step: this.stepStates
        ? this.stepStates.filter((state) => state === "COMPLETED").length
        : this.state === "SUCCEEDED"
          ? 2
          : 0,
      generation: 1,
      steps: this.stepStates
        ? this.stepStates.map((state, index) => ({
            id: `00000000-0000-4000-8000-00000000000${index}`,
            name: [
              "Read pipeline",
              "Score and segment",
              "Prepare summary",
              "Review results",
              "Post summary",
            ][index],
            state,
            ...(state === "COMPLETED" ? stepTimes[index] : {}),
            summary:
              state === "COMPLETED"
                ? `Finished ${[
                    "Read pipeline",
                    "Score and segment",
                    "Prepare summary",
                    "Review results",
                    "Post summary",
                  ][index].toLowerCase()}.`
                : null,
          }))
        : fixture.version.draft.steps.map((step, index) => ({
            id: step.id,
            name: step.name,
            ...(this.state === "SUCCEEDED" ? stepTimes[index] : {}),
            state: this.state === "SUCCEEDED" ? "COMPLETED" : "PENDING",
            summary:
              this.state === "SUCCEEDED"
                ? `Finished ${step.name.toLowerCase()}.`
                : null,
          })),
      final_summary:
        this.state === "SUCCEEDED"
          ? "Prepared the **weekly pipeline report** from the supplied period. 2 steps completed."
          : null,
      reason:
        this.runReason ??
        (this.state === "CANCELLED"
          ? "Cancelled; completed step summaries are preserved"
          : null),
      attempt: this.attempt,
      created_at: "2026-10-17T10:00:00Z",
      settled_at: ["SUCCEEDED", "CANCELLED", "FAILED"].includes(this.state)
        ? "2026-10-17T10:02:18Z"
        : null,
      rerun_of_run_id: null,
      // The server advertises Run again on settled runs and Cancel on the rest.
      allowed_actions: this.viewer
        ? []
        : ["SUCCEEDED", "CANCELLED", "FAILED"].includes(this.state)
          ? ["rerun"]
          : ["cancel"],
      ...over,
    });
    const rerunRun = () =>
      run({
        id: RERUN_ID,
        state: "QUEUED",
        revision: 1,
        next_step: 0,
        reason: null,
        final_summary: null,
        settled_at: null,
        attempt: null,
        rerun_of_run_id: RUN_ID,
        allowed_actions: ["cancel"],
        steps: fixture.version.draft.steps.map((step) => ({
          id: step.id,
          name: step.name,
          state: "PENDING",
          summary: null,
        })),
      });
    await this.page.route(`${base}/workflow-capabilities`, (route) =>
      route.fulfill({
        json: {
          authoring: true,
          execution: true,
          review_destinations: ["web"],
        },
      }),
    );
    await this.page.route(`${base}/workflows/${WORKFLOW_ID}`, (route) =>
      route.fulfill({
        json: {
          ...fixture,
          execution_available: true,
          allowed_actions: this.viewer ? [] : fixture.allowed_actions,
        },
      }),
    );
    await this.page.route(
      `${base}/workflows/${WORKFLOW_ID}/runs`,
      async (route) => {
        this.starts.push(route.request().postDataJSON());
        if (this.failStart) {
          this.failStart = false;
          await route.abort("failed");
          return;
        }
        await route.fulfill({ status: 202, json: run() });
      },
    );
    await this.page.route(`${base}/workflow-runs**`, async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (route.request().method() === "GET" && !path.endsWith("/history"))
        this.reads++;
      if (this.failRead || !path.includes(`/organizations/${TEST_ORG_ID}/`)) {
        await route.fulfill({ status: 404, json: { detail: "Run not found" } });
        return;
      }
      const page = (items: unknown[]) => ({
        items,
        total: items.length,
        page: 1,
        page_size: 20,
      });
      if (path.endsWith("/history") && path.includes(RERUN_ID)) {
        await route.fulfill({
          json: page([
            {
              id: "00000000-0000-4000-8000-0000000000b1",
              created_at: "2026-10-17T10:00:00Z",
              revision: 1,
              kind: "RERUN_STARTED",
              detail: "Re-run of run 12345678 using version 1",
            },
          ]),
        });
      } else if (path.endsWith("/history")) {
        await route.fulfill({
          json: page([
            {
              id: "00000000-0000-4000-8000-0000000000a1",
              created_at: "2026-10-17T10:00:00Z",
              revision: 1,
              kind: "STARTED",
              detail: "Run started using version 1",
            },
            {
              id: "00000000-0000-4000-8000-0000000000a2",
              created_at: "2026-10-17T10:01:00Z",
              revision: 2,
              kind: "ATTEMPT_FAILED",
              detail: "Pipedrive is not connected",
            },
          ]),
        });
      } else if (path.endsWith("/re-run")) {
        this.reruns.push(route.request().postDataJSON());
        if (this.failRerun) {
          this.failRerun = false;
          await route.abort("failed");
          return;
        }
        await route.fulfill({ status: 202, json: rerunRun() });
      } else if (path.endsWith(RERUN_ID)) {
        await route.fulfill({ json: rerunRun() });
      } else if (path.endsWith("/cancel")) {
        this.state = "CANCELLED";
        await route.fulfill({ json: run() });
      } else if (path.endsWith(RUN_ID)) await route.fulfill({ json: run() });
      else
        await route.fulfill({
          json: page(this.reruns.length ? [rerunRun(), run()] : [run()]),
        });
    });
  }
}
