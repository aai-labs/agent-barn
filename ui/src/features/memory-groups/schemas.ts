import { z } from "zod";

// A memory group is a named shared-memory pool: the agents in it see each other's
// memory. Membership is the opt-in.
export const MemoryGroupSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  organizationId: z.string().uuid(),
  createdAt: z.string(),
  updatedAt: z.string(),
});
export type MemoryGroup = z.infer<typeof MemoryGroupSchema>;

export const MemoryGroupsSchema = z.array(MemoryGroupSchema);

export type CreateMemoryGroupData = { name: string };
export type RenameMemoryGroupData = { id: string; name: string };
