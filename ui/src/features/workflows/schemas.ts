import { z } from "zod";

// The API counts Unicode code points; String.length counts UTF-16 units and
// would reject text the API accepts (an emoji is two units).
const limited = (empty: string, max: number) =>
  z
    .string()
    .trim()
    .min(1, empty)
    .refine((value) => [...value].length <= max, `Use ${max} characters or fewer`);

/**
 * Input limits apply while authoring. Saved snapshots are read back as stored,
 * so a limit mismatch can never hide a definition the API accepted.
 */
function draftSchema(authoring: boolean) {
  const text = authoring ? limited("Enter a description", 4000) : z.string();
  const name = authoring ? limited("Enter a name", 200) : z.string();
  const step = z.object({
    id: authoring ? z.guid() : z.string(),
    name,
    goal: text,
    // Drafts opened before this field was removed can still contain an empty value.
    completionCriteria: z.string().nullable().transform((value) =>
      value?.trim() ? value : undefined,
    ).optional(),
    artifactDescription: text.nullable().default(null),
    requiredCapabilities: z
      .array(z.enum(["reasoning", "business_action", "native_command"]))
      .min(1)
      .max(3)
      .default(["reasoning"]),
  });
  const input = z.object({
    // Label first: a blank label reports "Enter a name" rather than its derived key.
    label: name,
    // Derived from the label by inputKeyFromLabel; kept for saved snapshots.
    key: authoring
      ? z.string().regex(/^[a-z][a-z0-9_-]{0,63}$/, "Edit the input label")
      : z.string(),
    description: text,
    type: z.enum(["text", "number", "boolean", "file"]).default("text"),
    required: z.boolean().default(true),
  });
  return z.object({
    schemaVersion: z.literal(1).default(1),
    name,
    description: authoring
      ? z.string().trim().refine((value) => [...value].length <= 4000, "Use 4000 characters or fewer")
      : z.string(),
    steps: authoring
      ? z.array(step).min(1, "Add at least one step before saving").max(50)
      : z.array(step),
    inputs: (authoring ? z.array(input).max(30) : z.array(input)).default([]),
    reviewDestination: z.literal("web").default("web"),
  });
}
export const WorkflowDraftSchema = draftSchema(true).superRefine((draft, ctx) => {
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
const WorkflowStoredDraftSchema = draftSchema(false);
export const WorkflowVersionSchema = z.object({
  id: z.uuid(),
  number: z.number().int().positive(),
  createdAt: z.string(),
  createdByUserId: z.uuid().nullable(),
  draft: WorkflowStoredDraftSchema,
});
export const WorkflowSchema = z.object({
  id: z.uuid(),
  agentId: z.uuid(),
  revision: z.number().int().positive(),
  archivedAt: z.string().nullable(),
  version: WorkflowVersionSchema,
  allowedActions: z.array(z.enum(["save_version", "archive"])),
  executionAvailable: z.boolean(),
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
  execution: z.boolean(),
  reviewDestinations: z.array(z.literal("web")),
});
export type WorkflowDraft = z.infer<typeof WorkflowDraftSchema>;
export type WorkflowStep = WorkflowDraft["steps"][number];
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
