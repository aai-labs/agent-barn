import { z } from "zod";

export const WorkflowFileSchema = z.object({
  artifactId: z.uuid(),
  checksum: z.string(),
  filename: z.string(),
  size: z.number(),
});
export type WorkflowFile = z.infer<typeof WorkflowFileSchema>;
export type WorkflowInputValue =
  | string
  | number
  | boolean
  | Pick<WorkflowFile, "artifactId" | "checksum">;

/** One exact command a step's Agent asked a person to allow. */
export const WorkflowApprovalSchema = z.object({
  id: z.uuid(),
  stepIndex: z.number(),
  command: z.string(),
  state: z.enum(["LIVE", "PARKED", "APPROVED", "DECLINED", "RELEASED", "LAPSED"]),
  createdAt: z.string(),
  liveUntil: z.string(),
  decidedByUserId: z.uuid().nullable(),
  decidedAt: z.string().nullable(),
  guidance: z.string().nullable(),
});
export type WorkflowApproval = z.infer<typeof WorkflowApprovalSchema>;

/** One round at an Approval step: waiting for a person, or what they decided. */
export const WorkflowStepApprovalSchema = z.object({
  id: z.uuid(),
  stepIndex: z.number(),
  round: z.number(),
  state: z.enum(["WAITING", "APPROVED", "CHANGES_REQUESTED", "REJECTED", "LAPSED"]),
  createdAt: z.string(),
  decidedByUserId: z.uuid().nullable(),
  decidedAt: z.string().nullable(),
  note: z.string().nullable(),
});
export type WorkflowStepApproval = z.infer<typeof WorkflowStepApprovalSchema>;

export const WorkflowRunSchema = z.object({
  id: z.uuid(),
  workflowId: z.uuid(),
  versionId: z.uuid(),
  versionNumber: z.number(),
  name: z.string(),
  /** The run's own title, when the person starting it gave one. */
  title: z.string().nullable().optional(),
  /** The Agent that runs every step of this run. */
  agentId: z.uuid(),
  agentName: z.string(),
  /** The Agent was deleted: the run stays readable, with nothing left to do on it. */
  agentArchived: z.boolean(),
  initiatingUserId: z.uuid().nullable(),
  inputs: z.record(
    z.string(),
    z.union([z.string(), z.number(), z.boolean(), WorkflowFileSchema]),
  ),
  state: z.enum([
    "QUEUED",
    "RUNNING",
    "PAUSED",
    "BLOCKED",
    "AWAITING_APPROVAL",
    "CANCELLING",
    "CANCELLED",
    "SUCCEEDED",
    "FAILED",
    "REJECTED",
  ]),
  revision: z.number(),
  nextStep: z.number(),
  generation: z.number(),
  steps: z.array(
    z.object({
      id: z.uuid(),
      name: z.string(),
      /** An Approval step waits for a person instead of running in the Agent. */
      type: z.enum(["agent", "approval"]).default("agent"),
      state: z.enum(["PENDING", "RUNNING", "COMPLETED", "WAITING", "REJECTED"]),
      outputDescription: z.string().nullable().optional(),
      artifacts: z.array(WorkflowFileSchema).optional(),
      summary: z.string().nullable().optional(),
      startedAt: z.string().nullable().optional(),
      completedAt: z.string().nullable().optional(),
      /** The current round; above 1 once a person requested changes. */
      round: z.number().nullable().optional(),
      /** What the person deciding at an Approval step should check. */
      instructions: z.string().nullable().optional(),
      /** What the person at an Approval step may decide. */
      allowedDecisions: z
        .array(z.enum(["approve", "request_changes", "reject"]))
        .nullable()
        .optional(),
      /** Results sent back with Request changes, oldest first. */
      earlierRounds: z
        .array(
          z.object({
            round: z.number(),
            summary: z.string().nullable(),
            artifacts: z.array(WorkflowFileSchema),
            completedAt: z.string(),
          }),
        )
        .optional(),
    }),
  ),
  reason: z.string().nullable(),
  finalOutputDescription: z.string().nullable().optional(),
  finalArtifacts: z.array(WorkflowFileSchema).optional(),
  finalSummary: z.string().nullable().optional(),
  createdAt: z.string(),
  settledAt: z.string().nullable(),
  allowedActions: z.array(z.enum(["cancel", "rerun", "decide", "decide_step"])),
  /** The run this one repeats, when it was started with Run again. */
  rerunOfRunId: z.uuid().nullable().optional(),
  attempt: z
    .object({
      number: z.number(),
      startedAt: z.string(),
      expiresAt: z.string(),
      serverTime: z.string(),
      agentUnresponsive: z.boolean(),
    })
    .nullable()
    .optional(),
  /** The current step's latest approval request; on list reads only while it awaits a decision. */
  approval: WorkflowApprovalSchema.nullable().optional(),
  /** Every approval request of the run, oldest first (single-run read only). */
  approvals: z.array(WorkflowApprovalSchema).optional(),
  /** The Approval step round awaiting a decision, when the run waits at one. */
  stepApproval: WorkflowStepApprovalSchema.nullable().optional(),
  /** Every Approval step round of the run, oldest first (single-run read only). */
  stepApprovals: z.array(WorkflowStepApprovalSchema).optional(),
});
export const WorkflowRunHistorySchema = z.object({
  items: z.array(
    z.object({
      id: z.uuid(),
      createdAt: z.string(),
      kind: z.string(),
      detail: z.string(),
    }),
  ),
  total: z.number(),
});
export type WorkflowRunHistory = z.infer<typeof WorkflowRunHistorySchema>;
export const WorkflowRunListSchema = z.object({
  items: z.array(WorkflowRunSchema),
  total: z.number(),
  page: z.number(),
  pageSize: z.number(),
});
export type WorkflowRun = z.infer<typeof WorkflowRunSchema>;
export const runStateLabel = (state: WorkflowRun["state"]) =>
  ({
    QUEUED: "Queued",
    RUNNING: "Running",
    PAUSED: "Paused",
    BLOCKED: "Needs attention",
    AWAITING_APPROVAL: "Awaiting approval",
    CANCELLING: "Cancelling",
    CANCELLED: "Cancelled",
    SUCCEEDED: "Completed",
    FAILED: "Failed",
    REJECTED: "Rejected",
  })[state];
export type WorkflowRunList = z.infer<typeof WorkflowRunListSchema>;
export const isRunTerminal = (state: string) =>
  ["SUCCEEDED", "FAILED", "CANCELLED", "REJECTED"].includes(state);
export const isRunProgressing = (state: string) =>
  ["QUEUED", "RUNNING", "CANCELLING"].includes(state);

/** What a run is called in lists: its own title, else its workflow's name. */
export const runTitle = (run: Pick<WorkflowRun, "title" | "name">) =>
  run.title?.trim() || run.name;

/** The request a person can still decide: live while the session holds it, parked once it stopped. */
export const pendingApproval = (run: WorkflowRun) =>
  run.approval && ["LIVE", "PARKED"].includes(run.approval.state)
    ? run.approval
    : null;

/** The Approval step round awaiting a person's decision, if the run waits at one. */
export const waitingStepApproval = (run: WorkflowRun) =>
  run.stepApproval?.state === "WAITING" ? run.stepApproval : null;

/** Whether this viewer can decide something on the run right now: a command or an Approval step. */
export const waitsOnViewer = (run: WorkflowRun) =>
  run.allowedActions.includes("decide") || run.allowedActions.includes("decide_step");
