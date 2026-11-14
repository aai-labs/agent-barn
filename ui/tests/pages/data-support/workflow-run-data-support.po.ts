import { type Page } from "@playwright/test";
import { workflowFixture, WORKFLOW_ID } from "../../fixtures/workflows";
import { artifactFixture } from "../../fixtures/artifacts";
import { TEST_ORG_ID } from "../../constants";

export const RUN_ID = "12345678-1234-4234-8234-123456789abc";
export const RERUN_ID = "87654321-4321-4432-8432-cba987654321";
export const OTHER_RUN_ID = "0f0f0f0f-1234-4234-8234-123456789abc";
const stepTimes = [
  { started_at: "2026-10-17T10:00:00Z", completed_at: "2026-10-17T10:01:54Z" },
  { started_at: "2026-10-17T10:01:54Z", completed_at: "2026-10-17T10:02:18Z" },
];
export class WorkflowRunDataSupport {
  fileInputs = false;
  storageState = "READY";
  storageLimit = 26214400;
  provisionRequests = 0;
  failUpload = false;
  /** Holds an upload open until it resolves, to act while a file is still uploading. */
  uploadGate: Promise<void> | null = null;
  uploadedBytes: Buffer | null = null;
  uploaded = { ...artifactFixture };
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
  failHistory = false;
  /** The current step's approval request, as the API reads it. */
  approval: Record<string, unknown> | null = null;
  /** Every request of the run, as the single-run read lists them. */
  approvals: Record<string, unknown>[] = [];
  decisions: Record<string, unknown>[] = [];
  /** The output an older version's steps were asked for. */
  outputDescription: string | null = null;
  /** The run's own title, when one was given at start. */
  title: string | null = null;
  /** The run's Agent was deleted. */
  agentArchived = false;
  /** Query strings of run list reads, to assert the filters sent. */
  listQueries: string[] = [];
  /** A second run, on another Agent, listed beside the primary one. */
  otherAgentRun: { agent_id: string; agent_name: string } | null = null;
  /** The Agent the saved workflow starts runs with by default. */
  defaultAgentId: string | null = null;
  /** Overrides the step list with this many-step progression (for walkthrough captures). */
  stepStates: string[] | null = null;
  constructor(private page: Page) {}
  async intercept(agentId: string) {
    await this.page.route(`**/api/v1/organizations/*/agents/${agentId}/artifacts?**`, route => route.fulfill({json: {items: this.fileInputs ? [this.uploaded] : [], total: this.fileInputs ? 1 : 0, page: 1, page_size: 20}}));
    await this.page.route(`**/api/v1/organizations/*/agents/${agentId}/artifacts/storage`, async route => {
      if (route.request().method() === "POST") {
        this.provisionRequests++;
        this.storageState = "PROVISIONING";
      }
      await route.fulfill({json: {state: this.storageState, max_bytes: this.storageLimit}});
    });
    const filesBase = `**/api/v1/organizations/*/agents/${agentId}/artifacts`;
    await this.page.route(filesBase, async route => {
      this.uploaded = { ...artifactFixture, ...route.request().postDataJSON() };
      await route.fulfill({ status: 201, json: { ...this.uploaded, state: "UPLOADING" } });
    });
    await this.page.route(`${filesBase}/*/content`, async route => {
      this.uploadedBytes = route.request().postDataBuffer();
      await this.uploadGate;
      await route.fulfill({ status: this.failUpload ? 503 : 200, json: this.failUpload ? { detail: "Storage unavailable" } : this.uploaded });
    });
    const fixture = workflowFixture(this.defaultAgentId);
    const base = `**/api/v1/organizations/*`;
    const run = (over: Record<string, unknown> = {}) => ({
      id: RUN_ID,
      workflow_id: WORKFLOW_ID,
      version_id: fixture.version.id,
      version_number: 1,
      name: fixture.version.draft.name,
      title: this.title,
      agent_id: agentId,
      agent_name: "Maya",
      agent_archived: this.agentArchived,
      initiating_user_id: null,
      inputs: this.fileInputs ? { period: { artifact_id: this.uploaded.id, checksum: this.uploaded.checksum, filename: this.uploaded.filename, size: this.uploaded.size } } : { period: "This week" },
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
            output_description: this.outputDescription,
            artifacts: this.fileInputs && this.state === "SUCCEEDED" ? [{ artifact_id: artifactFixture.id, checksum: artifactFixture.checksum, filename: artifactFixture.filename, size: artifactFixture.size }] : [],
            summary:
              this.state === "SUCCEEDED"
                ? `Finished ${step.name.toLowerCase()}.`
                : null,
          })),
      final_artifacts: this.fileInputs && this.state === "SUCCEEDED" ? [{ artifact_id: artifactFixture.id, checksum: artifactFixture.checksum, filename: artifactFixture.filename, size: artifactFixture.size }] : [],
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
      approval: this.approval,
      approvals: this.approvals,
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
          : ["LIVE", "PARKED"].includes(String(this.approval?.state))
            ? ["decide", "cancel"]
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
          version: { ...fixture.version, draft: { ...fixture.version.draft, inputs: this.fileInputs ? fixture.version.draft.inputs.map(input => ({ ...input, type: "file" })) : fixture.version.draft.inputs } },
          execution_available: true,
          allowed_actions: this.viewer ? [] : fixture.allowed_actions,
        },
      }),
    );
    await this.page.route(`${base}/workflow-runs**`, async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (route.request().method() === "POST" && path.endsWith("/workflow-runs")) {
        const body = route.request().postDataJSON();
        this.starts.push(body);
        if (this.failStart) {
          this.failStart = false;
          await route.abort("failed");
          return;
        }
        this.title = body.title ?? null;
        await route.fulfill({ status: 202, json: run({ agent_id: body.agent_id }) });
        return;
      }
      // The approvals badge polls on its own schedule; reads count only the runs themselves.
      const awaiting = new URL(route.request().url()).searchParams.has("awaiting_decision");
      if (route.request().method() === "GET" && !path.endsWith("/history") && !awaiting)
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
      if (path.endsWith("/history") && this.failHistory) {
        await route.fulfill({
          status: 500,
          json: { detail: "History unavailable" },
        });
      } else if (path.endsWith("/history") && path.includes(RERUN_ID)) {
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
          json: page(
          [
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
            ...(this.approval
              ? [
                  {
                    id: "00000000-0000-4000-8000-0000000000a4",
                    created_at: "2026-10-17T10:01:30Z",
                    revision: 3,
                    kind: "APPROVAL_REQUESTED",
                    detail: `Approval requested to run ${this.approval.command}`,
                  },
                ]
              : []),
            ...(this.state === "SUCCEEDED"
              ? [
                  {
                    id: "00000000-0000-4000-8000-0000000000a3",
                    created_at: "2026-10-17T10:02:18Z",
                    revision: 3,
                    kind: "STEP_COMPLETED",
                    detail: "## Final step\n\n[Open the report](https://example.test)",
                  },
                ]
              : []),
          ].reverse(),
          ),
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
      } else if (path.endsWith("/decision")) {
        const body = route.request().postDataJSON();
        this.decisions.push(body);
        const late = this.approval?.state === "PARKED";
        this.approval = { ...this.approval, state: body.decision === "approve" ? "APPROVED" : "DECLINED", guidance: body.guidance ?? null };
        if (late) this.state = "QUEUED";
        await route.fulfill({ json: run() });
      } else if (path.endsWith("/cancel")) {
        this.state = "CANCELLED";
        await route.fulfill({ json: run() });
      } else if (path.endsWith(RUN_ID)) await route.fulfill({ json: run() });
      else if (new URL(route.request().url()).searchParams.get("awaiting_decision") === "true")
        await route.fulfill({
          json: page(["LIVE", "PARKED"].includes(String(this.approval?.state)) ? [run()] : []),
        });
      else {
        const query = new URL(route.request().url()).searchParams;
        this.listQueries.push(query.toString());
        const settled = ["SUCCEEDED", "CANCELLED", "FAILED"];
        const items = [
          ...(this.reruns.length ? [rerunRun()] : []),
          run(),
          ...(this.otherAgentRun
            ? [run({ id: OTHER_RUN_ID, ...this.otherAgentRun })]
            : []),
        ].filter(
          (item) =>
            (!query.get("agent_id") || item.agent_id === query.get("agent_id")) &&
            (!query.get("status") ||
              settled.includes(String(item.state)) === (query.get("status") === "settled")),
        );
        await route.fulfill({ json: page(items) });
      }
    });
  }
}
