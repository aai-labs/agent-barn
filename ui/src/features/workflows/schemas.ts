import { z } from "zod";

const text = z.string().trim().min(1, "Enter a description").max(4000);
const name = z.string().trim().min(1, "Enter a name").max(200);
export const WorkflowStepSchema = z.object({
  id: z.guid(),
  name,
  goal: text,
  completionCriteria: text,
  artifactDescription: text.nullable().default(null),
  requiredCapabilities: z
    .array(z.enum(["reasoning", "business_action", "native_command"]))
    .min(1)
    .max(3)
    .default(["reasoning"]),
});
export const WorkflowInputSchema = z.object({
  // Label first: a blank label reports "Enter a name" rather than its derived key.
  label: name,
  // Derived from the label by inputKeyFromLabel; kept for saved snapshots.
  key: z.string().regex(/^[a-z][a-z0-9_-]{0,63}$/, "Edit the input label"),
  description: text,
  type: z.enum(["text", "number", "boolean"]).default("text"),
  required: z.boolean().default(true),
});
export const WorkflowDraftSchema = z
  .object({
    schemaVersion: z.literal(1).default(1),
    name,
    description: text,
    steps: z
      .array(WorkflowStepSchema)
      .min(1, "Add at least one step before saving")
      .max(50),
    inputs: z.array(WorkflowInputSchema).max(30).default([]),
    finalArtifactDescription: text.nullable().default(null),
    reviewDestination: z.literal("web").default("web"),
  })
  .superRefine((draft, ctx) => {
    if (new Set(draft.steps.map((s) => s.id)).size !== draft.steps.length)
      ctx.addIssue({
        code: "custom",
        path: ["steps"],
        message: "Each step needs a unique id",
      });
    const firstWithKey = new Map<string, number>();
    draft.inputs.forEach(({ key }, index) => {
      const first = firstWithKey.get(key);
      if (first === undefined) firstWithKey.set(key, index);
      else if (key)
        ctx.addIssue({
          code: "custom",
          path: ["inputs", index, "label"],
          message: `Matches input ${first + 1} once case, accents and punctuation are ignored; use a distinct label`,
        });
    });
  });
export const WorkflowVersionSchema = z.object({
  id: z.uuid(),
  number: z.number().int().positive(),
  createdAt: z.string(),
  createdByUserId: z.uuid().nullable(),
  draft: WorkflowDraftSchema,
});
export const WorkflowSchema = z.object({
  id: z.uuid(),
  agentId: z.uuid(),
  revision: z.number().int().positive(),
  archivedAt: z.string().nullable(),
  version: WorkflowVersionSchema,
  allowedActions: z.array(z.enum(["save_version", "archive"])),
  executionAvailable: z.literal(false),
});
export const WorkflowSummarySchema = WorkflowSchema.extend({
  version: z.object({
    id: z.uuid(),
    number: z.number().int().positive(),
    createdAt: z.string(),
    createdByUserId: z.uuid().nullable(),
    name: z.string(),
    description: z.string(),
    stepCount: z.number().int().nonnegative(),
    inputCount: z.number().int().nonnegative(),
  }),
});
export const WorkflowListSchema = z.object({
  items: z.array(WorkflowSummarySchema),
  total: z.number(),
  page: z.number(),
  pageSize: z.number(),
});
export const WorkflowCapabilitiesSchema = z.object({
  authoring: z.boolean(),
  execution: z.literal(false),
  reviewDestinations: z.array(z.literal("web")),
});
export type WorkflowDraft = z.infer<typeof WorkflowDraftSchema>;
export type WorkflowStep = z.infer<typeof WorkflowStepSchema>;
export type Workflow = z.infer<typeof WorkflowSchema>;
export type WorkflowSummary = z.infer<typeof WorkflowSummarySchema>;
export type WorkflowList = z.infer<typeof WorkflowListSchema>;
export type WorkflowVersion = z.infer<typeof WorkflowVersionSchema>;

export const WorkflowVersionListSchema = z.object({
  items: z.array(WorkflowVersionSchema),
  total: z.number(),
  page: z.number(),
  pageSize: z.number(),
});
export type WorkflowVersionList = z.infer<typeof WorkflowVersionListSchema>;
export type WorkflowCapabilities = z.infer<typeof WorkflowCapabilitiesSchema>;

export const PlatformWorkflowSettingsSchema = z.object({
  authoringEnabled: z.boolean(),
  updatedAt: z.string().nullable(),
});
export type PlatformWorkflowSettings = z.infer<typeof PlatformWorkflowSettingsSchema>;
