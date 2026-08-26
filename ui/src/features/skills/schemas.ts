import { z } from "zod";

export const SkillSourceSchema = z.enum(["aai_cli", "custom"]);
export const SkillScopeSchema = z.enum(["platform", "organization", "agent"]);

export const SkillSchema = z.object({
  id: z.string().uuid(),
  organizationId: z.string().uuid().nullable(),
  agentId: z.string().uuid().nullable().optional(),
  scope: SkillScopeSchema,
  name: z.string(),
  slug: z.string(),
  description: z.string().nullable(),
  // Directory the skill's files are written to in the agent workspace.
  rootDir: z.string(),
  entryPath: z.string(),
  source: SkillSourceSchema,
  requiredProviders: z.array(z.string()),
  toolsPointer: z.string().nullable(),
  version: z.number().int().min(1).nullable(),
  hasDraft: z.boolean(),
  sourceSkillId: z.string().uuid().nullable().optional(),
  sourceSkillVersion: z.number().int().nullable().optional(),
  updateAvailable: z.boolean().default(false),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const SkillFileSchema = z.object({
  // Path relative to the skill root, e.g. "SKILL.md" or "helpers/notes.md".
  path: z.string(),
  content: z.string(),
});

export const SkillDetailSchema = SkillSchema.extend({
  files: z.array(SkillFileSchema),
  // Whether a non-soft-deleted agent in the caller's organization has this skill
  // assigned; gates deleting the currently published version.
  isAssignedToAgent: z.boolean(),
});

export const SkillVersionSchema = z.object({
  version: z.number().int().min(1),
  description: z.string().nullable().optional(),
  requiredProviders: z.array(z.string()).default([]),
  sourceSkillId: z.string().uuid().nullable().optional(),
  sourceSkillVersion: z.number().int().nullable().optional(),
  createdBy: z.string().uuid().nullable(),
  createdAt: z.string(),
  isPinnedByAgent: z.boolean(),
});

export const SkillDraftSchema = z.object({
  skillId: z.string().uuid(),
  files: z.array(SkillFileSchema),
  description: z.string().nullable(),
  requiredProviders: z.array(z.string()),
  sourceSkillId: z.string().uuid().nullable().optional(),
  sourceSkillVersion: z.number().int().nullable().optional(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const PaginatedSkillsSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(SkillSchema),
});

export type Skill = z.infer<typeof SkillSchema>;
export type SkillFile = z.infer<typeof SkillFileSchema>;
export type SkillDetail = z.infer<typeof SkillDetailSchema>;
export type SkillVersion = z.infer<typeof SkillVersionSchema>;
export type SkillDraft = z.infer<typeof SkillDraftSchema>;
export type SkillSource = z.infer<typeof SkillSourceSchema>;
export type SkillScope = z.infer<typeof SkillScopeSchema>;
export type PaginatedSkills = z.infer<typeof PaginatedSkillsSchema>;
