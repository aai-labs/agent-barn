import { type Page } from "@playwright/test";
import { workflowFixture, WORKFLOW_ID } from "../../fixtures/workflows";
import { TEST_ORG_ID } from "../../constants";

export const RUN_ID = "12345678-1234-4234-8234-123456789abc";
const stepTimes = [
  { started_at: "2026-10-17T10:00:00Z", completed_at: "2026-10-17T10:01:54Z" },
  { started_at: "2026-10-17T10:01:54Z", completed_at: "2026-10-17T10:02:18Z" },
];
export class WorkflowRunDataSupport {
  starts: Record<string, unknown>[] = [];
  failStart = false;
  failRead = false;
  viewer = false;
  state = "RUNNING";
  /** Overrides the step list with this many-step progression (for walkthrough captures). */
  stepStates: string[] | null = null;
  constructor(private page: Page) {}
  async intercept(agentId: string) {
    const fixture = workflowFixture(agentId);
    const base = `**/api/v1/organizations/*/agents/${agentId}`;
    const run = () => ({
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
        this.state === "CANCELLED"
          ? "Cancelled; completed step summaries are preserved"
          : null,
      created_at: "2026-10-17T10:00:00Z",
      settled_at: ["SUCCEEDED", "CANCELLED", "FAILED"].includes(this.state)
        ? "2026-10-17T10:02:18Z"
        : null,
      allowed_actions:
        this.viewer || this.state === "SUCCEEDED" || this.state === "CANCELLED"
          ? []
          : ["cancel"],
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
      if (path.endsWith("/cancel")) {
        this.state = "CANCELLED";
        await route.fulfill({ json: run() });
      } else if (path.endsWith(RUN_ID)) await route.fulfill({ json: run() });
      else await route.fulfill({ json: page([run()]) });
    });
  }
}
