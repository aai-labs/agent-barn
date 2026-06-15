import { z } from "zod";

export const SkillSourceSchema = z.enum(["aai_cli", "custom"]);

export const SkillSchema = z.object({
  id: z.string().uuid(),
  organizationId: z.string().uuid().nullable(),
  name: z.string(),
  source: SkillSourceSchema,
  requiredProviders: z.array(z.string()),
  toolsPointer: z.string().nullable(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const SkillsListSchema = z.array(SkillSchema);

export type Skill = z.infer<typeof SkillSchema>;
export type SkillSource = z.infer<typeof SkillSourceSchema>;