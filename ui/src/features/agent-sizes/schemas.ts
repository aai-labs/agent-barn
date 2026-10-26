import { z } from "zod";

/** One size in the Agent Size catalog. CPU in millicores, memory in bytes, as the API keeps them. */
export const AgentSizeSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  cpuRequestMillicores: z.number().int(),
  cpuLimitMillicores: z.number().int(),
  memoryRequestBytes: z.number().int(),
  memoryLimitBytes: z.number().int(),
  enabled: z.boolean(),
  isDefault: z.boolean(),
  sortOrder: z.number().int(),
  createdAt: z.string(),
  updatedAt: z.string(),
  /** Live Agents whose stored size this is; one Organization's when the catalog was read for one. */
  agentCount: z.number().int(),
  /** On the default only: live Agents that follow it, and move when another size becomes it. */
  followingAgentCount: z.number().int(),
});
export type AgentSize = z.infer<typeof AgentSizeSchema>;

export const AgentSizeListSchema = z.array(AgentSizeSchema);

/** What a size is made of; the dialog edits these. */
export type AgentSizeValues = Pick<
  AgentSize,
  "name" | "cpuRequestMillicores" | "cpuLimitMillicores" | "memoryRequestBytes" | "memoryLimitBytes"
>;

export type AgentSizeCreate = AgentSizeValues & { enabled?: boolean };

/** A partial edit; `isDefault` only ever true, since another size becoming the default is how one stops being it. */
export type AgentSizeUpdate = Partial<AgentSizeValues & { enabled: boolean; isDefault: true; sortOrder: number }>;

/** A size as an Organization sees it, on an Agent and in what it may choose. */
export const AgentSizeOptionSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  cpuRequestMillicores: z.number().int(),
  cpuLimitMillicores: z.number().int(),
  memoryRequestBytes: z.number().int(),
  memoryLimitBytes: z.number().int(),
  isDefault: z.boolean(),
});
export type AgentSizeOption = z.infer<typeof AgentSizeOptionSchema>;

/** What an Organization's Agents may be put on: the default first. `canChoose` is false when that is all. */
export const OrganizationAgentSizesSchema = z.object({
  canChoose: z.boolean(),
  sizes: z.array(AgentSizeOptionSchema),
});
export type OrganizationAgentSizes = z.infer<typeof OrganizationAgentSizesSchema>;
