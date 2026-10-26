import { z } from "zod";

export const WorkflowRunSchema = z.object({
  id: z.uuid(),
  workflowId: z.uuid(),
  versionId: z.uuid(),
  versionNumber: z.number(),
  name: z.string(),
  initiatingUserId: z.uuid().nullable(),
  inputs: z.record(z.string(), z.union([z.string(), z.number(), z.boolean()])),
  state: z.enum([
    "QUEUED",
    "RUNNING",
    "PAUSED",
    "BLOCKED",
    "CANCELLING",
    "CANCELLED",
    "SUCCEEDED",
    "FAILED",
  ]),
  revision: z.number(),
  nextStep: z.number(),
  generation: z.number(),
  steps: z.array(
    z.object({
      id: z.uuid(),
      name: z.string(),
      state: z.enum(["PENDING", "RUNNING", "COMPLETED"]),
      summary: z.string().nullable().optional(),
      startedAt: z.string().nullable().optional(),
      completedAt: z.string().nullable().optional(),
    }),
  ),
  reason: z.string().nullable(),
  finalSummary: z.string().nullable().optional(),
  createdAt: z.string(),
  settledAt: z.string().nullable(),
  allowedActions: z.array(z.literal("cancel")),
  attempt: z
    .object({
      number: z.number(),
      limit: z.number(),
      startedAt: z.string(),
      expiresAt: z.string(),
      agentUnresponsive: z.boolean(),
    })
    .nullable()
    .optional(),
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
    CANCELLING: "Cancelling",
    CANCELLED: "Cancelled",
    SUCCEEDED: "Completed",
    FAILED: "Failed",
  })[state];
export type WorkflowRunList = z.infer<typeof WorkflowRunListSchema>;
export const isRunTerminal = (state: string) =>
  ["SUCCEEDED", "FAILED", "CANCELLED"].includes(state);
export const isRunProgressing = (state: string) =>
  ["QUEUED", "RUNNING", "CANCELLING"].includes(state);
