import { z } from "zod";

export const PlaybookExtractionStatusSchema = z.enum(["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]);

export const PlaybookExtractionErrorSchema = z.enum([
  "enqueue_failed",
  "requester_lost_access",
  "source_agent_unavailable",
  "no_sessions",
  "model_unavailable",
  "spend_limit_reached",
  "model_error",
  "answer_truncated",
  "interrupted",
  "draft_conflict",
  "skill_unavailable",
  "internal_error",
]);

export const PlaybookExtractionSchema = z.object({
  id: z.string().uuid(),
  organizationId: z.string().uuid(),
  sourceAgentId: z.string().uuid(),
  sourceAgentName: z.string(),
  skillId: z.string().uuid().nullable(),
  skillName: z.string(),
  status: PlaybookExtractionStatusSchema,
  // Codes added later are shown generically rather than failing the whole list.
  errorCode: z.string().nullable(),
  windowStart: z.string(),
  windowEnd: z.string(),
  maxSessions: z.number().int(),
  model: z.string().nullable(),
  sessionCount: z.number().int(),
  messageCount: z.number().int(),
  toolCallCount: z.number().int(),
  memoryCount: z.number().int(),
  inputChars: z.number().int(),
  promptTokens: z.number().int(),
  completionTokens: z.number().int(),
  // Decimals arrive as strings.
  costUsd: z.coerce.number().nullable(),
  requestedByUserId: z.string().uuid().nullable(),
  conventionCount: z.number().int().default(0),
  // Whether the target Skill has an unpublished draft now; set on run lists.
  skillHasDraft: z.boolean().default(false),
  createdAt: z.string(),
  startedAt: z.string().nullable(),
  finishedAt: z.string().nullable(),
});

export const PlaybookConventionSchema = z.object({
  rule: z.string(),
  conversations: z.number().int(),
});

export const PlaybookExtractionDetailSchema = PlaybookExtractionSchema.extend({
  resultMarkdown: z.string().nullable(),
  conventions: z.array(PlaybookConventionSchema).default([]),
});

export const ConventionsAppliedSchema = z.object({
  templateKey: z.string(),
  added: z.number().int(),
  alreadyPresent: z.number().int(),
});

export const PaginatedPlaybookExtractionsSchema = z.object({
  items: z.array(PlaybookExtractionSchema),
  page: z.number().int(),
  pageSize: z.number().int(),
  total: z.number().int(),
});

export const PlaybookExtractionPreviewSchema = z.object({
  windowStart: z.string(),
  windowEnd: z.string(),
  sessionCount: z.number().int(),
  messageCount: z.number().int(),
  toolCallCount: z.number().int(),
  inputChars: z.number().int(),
  estimatedInputTokens: z.number().int(),
  estimatedOutputTokens: z.number().int(),
  model: z.string(),
});

export const PlaybookExtractionCreateSchema = z.union([
  z.object({ skillName: z.string().trim().min(1).max(255), windowDays: z.number().int(), maxSessions: z.number().int() }),
  z.object({ skillId: z.string().uuid(), windowDays: z.number().int(), maxSessions: z.number().int() }),
]);

export const PlatformPlaybookSettingsSchema = z.object({
  model: z.string(),
  updatedAt: z.string().nullable().optional(),
});
export const PlatformPlaybookModelsSchema = z.array(z.object({ value: z.string(), label: z.string() }));

export type PlaybookExtractionStatus = z.infer<typeof PlaybookExtractionStatusSchema>;
export type PlaybookExtractionError = z.infer<typeof PlaybookExtractionErrorSchema>;
export type PlaybookExtraction = z.infer<typeof PlaybookExtractionSchema>;
export type PlaybookExtractionDetail = z.infer<typeof PlaybookExtractionDetailSchema>;
export type PlaybookConvention = z.infer<typeof PlaybookConventionSchema>;
export type ConventionsApplied = z.infer<typeof ConventionsAppliedSchema>;
export type PaginatedPlaybookExtractions = z.infer<typeof PaginatedPlaybookExtractionsSchema>;
export type PlaybookExtractionPreview = z.infer<typeof PlaybookExtractionPreviewSchema>;
export type PlaybookExtractionCreate = z.infer<typeof PlaybookExtractionCreateSchema>;
export type PlatformPlaybookSettings = z.infer<typeof PlatformPlaybookSettingsSchema>;
export type PlatformPlaybookModels = z.infer<typeof PlatformPlaybookModelsSchema>;
