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
