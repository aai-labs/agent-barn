import { z } from "zod";

const TemplateSkillSchema = z.object({
  id: z.string().uuid(),
  organizationId: z.string().uuid().nullable(),
  name: z.string(),
  source: z.enum(["aai_cli", "custom"]),
  requiredProviders: z.array(z.string()),
  toolsPointer: z.string().nullable(),
  version: z.number().int().min(1).nullable(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

const TemplateRequiredSkillSchema = TemplateSkillSchema.extend({
  // A required Skill must always point at an exact published version.
  version: z.number().int().min(1),
  groupKey: z.string().nullable().optional().default(null),
});

export const TemplateLineageSummarySchema = z.object({
  templateKey: z.string(),
  templateName: z.string(),
  latestPublishedVersion: z.number().int().nullable(),
  hasDraft: z.boolean(),
  templateSource: z.enum(["pre-defined", "custom"]).optional(),
  isFork: z.boolean().optional(),
  platformUpdateAvailable: z.boolean().optional(),
  inUse: z.boolean().optional(),
});

export const TemplateLineageSummariesSchema = z.array(
  TemplateLineageSummarySchema,
);

export const TemplateDraftReadSchema = z.object({
  id: z.string().uuid(),
  templateKey: z.string(),
  templateName: z.string(),
  description: z.string().nullable(),
  soulMd: z.string(),
  identityMd: z.string(),
  userMd: z.string(),
  toolsMd: z.string(),
  agentsMd: z.string(),
  bootMd: z.string(),
  bootstrapMd: z.string(),
  heartbeatMd: z.string(),
  createdAt: z.string(),
  updatedAt: z.string(),
  requiredSkills: z.array(TemplateRequiredSkillSchema).default([]),
});

export const TemplateReadSchema = z.object({
  id: z.string().uuid(),
  organizationId: z.string().uuid().nullable(),
  templateKey: z.string(),
  templateName: z.string(),
  templateSource: z.enum(["pre-defined", "custom"]),
  forkedFromPlatformTemplateId: z.string().uuid().nullable().optional(),
  forkBaselinePlatformTemplateId: z.string().uuid().nullable().optional(),
  forkBaselinePlatformVersion: z.number().int().nullable().optional(),
  version: z.number().int(),
  description: z.string().nullable(),
  soulMd: z.string(),
  identityMd: z.string(),
  userMd: z.string(),
  toolsMd: z.string(),
  agentsMd: z.string(),
  bootMd: z.string(),
  bootstrapMd: z.string(),
  heartbeatMd: z.string(),
  createdAt: z.string(),
  updatedAt: z.string(),
  requiredSkills: z.array(TemplateRequiredSkillSchema).default([]),
  inUse: z.boolean().default(false),
});

export const TemplatePublishedReadSchema = z.object({
  id: z.string().uuid(),
  templateKey: z.string(),
  version: z.number().int(),
});

export const TemplateSkillListSchema = z.array(TemplateSkillSchema);

export const PaginatedTemplateSkillsSchema = z.object({
  page: z.number().int(),
  pageSize: z.number().int(),
  total: z.number().int(),
  items: z.array(TemplateSkillSchema),
});

export type TemplateLineageSummary = z.infer<
  typeof TemplateLineageSummarySchema
>;
export type TemplateDraft = z.infer<typeof TemplateDraftReadSchema>;
export type TemplateRead = z.infer<typeof TemplateReadSchema>;
export type TemplateSkill = z.infer<typeof TemplateSkillListSchema>[number];

export type TemplateDraftFields = {
  description?: string | null;
  soulMd?: string;
  identityMd?: string;
  userMd?: string;
  toolsMd?: string;
  agentsMd?: string;
  bootMd?: string;
  bootstrapMd?: string;
  heartbeatMd?: string;
  requiredSkillIds?: string[];
  requiredSkillGroups?: { groupKey: string; skillIds: string[] }[];
  requiredSkillVersions?: Record<string, number>;
};

export type CreateTemplateDraft = TemplateDraftFields & {
  templateName: string;
};
