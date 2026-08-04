import { z } from "zod";

const PlatformTemplateSkillSchema = z.object({
  id: z.string().uuid(),
  organizationId: z.string().uuid().nullable(),
  name: z.string(),
  source: z.enum(["aai_cli", "custom"]),
  requiredProviders: z.array(z.string()),
  toolsPointer: z.string().nullable(),
  createdAt: z.string(),
  updatedAt: z.string(),
  groupKey: z.string().nullable().optional().default(null),
});

export const PlatformTemplateAdminSummarySchema = z.object({
  templateKey: z.string(),
  templateName: z.string(),
  latestPublishedVersion: z.number().int().nullable(),
  hasDraft: z.boolean(),
});

export const PlatformTemplateAdminSummariesSchema = z.array(
  PlatformTemplateAdminSummarySchema,
);

export const PlatformTemplateDraftReadSchema = z.object({
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
  requiredSkills: z.array(PlatformTemplateSkillSchema).default([]),
});

export const PlatformTemplateReadSchema = z.object({
  id: z.string().uuid(),
  organizationId: z.string().uuid().nullable(),
  templateKey: z.string(),
  templateName: z.string(),
  templateSource: z.literal("pre-defined"),
  forkedFromPlatformTemplateId: z.string().uuid().nullable().optional(),
  forkBaselinePlatformTemplateId: z.string().uuid().nullable().optional(),
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
  requiredSkills: z.array(PlatformTemplateSkillSchema).default([]),
  inUse: z.boolean().default(false),
});

export const PlatformTemplatePublishedReadSchema = z.object({
  id: z.string().uuid(),
  templateKey: z.string(),
  version: z.number().int(),
});

export const PlatformSkillListSchema = z.array(PlatformTemplateSkillSchema.omit({ groupKey: true }));

export type PlatformTemplateAdminSummary = z.infer<
  typeof PlatformTemplateAdminSummarySchema
>;
export type PlatformTemplateDraft = z.infer<typeof PlatformTemplateDraftReadSchema>;
export type PlatformTemplate = z.infer<typeof PlatformTemplateReadSchema>;
export type PlatformSkill = z.infer<typeof PlatformSkillListSchema>[number];

export type PlatformTemplateDraftFields = {
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
};

export type CreatePlatformTemplateDraft = PlatformTemplateDraftFields & {
  templateName: string;
};
