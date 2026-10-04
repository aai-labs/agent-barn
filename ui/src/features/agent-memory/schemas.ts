import { z } from "zod";

export const AgentMemoryStateSchema = z.object({
  agentId: z.string().uuid(),
  enabled: z.boolean(),
});

export const MemoryGrantSchema = z.object({
  id: z.string().uuid(),
  agentId: z.string().uuid(),
  agentName: z.string(),
  /** Null for an Organization Memory grant. */
  sourceAgentId: z.string().uuid().nullable(),
  sourceAgentName: z.string().nullable(),
  createdAt: z.string(),
});

export const MemoryGrantListSchema = z.array(MemoryGrantSchema);

export const MemoryItemTypeSchema = z.enum(["world", "experience", "observation"]);

export const MemoryItemSchema = z.object({
  id: z.string(),
  type: MemoryItemTypeSchema,
  text: z.string(),
  /** When Hindsight recorded the memory as mentioned; not necessarily when it was stored. */
  mentionedAt: z.string().nullable(),
  /** True for Organization Memory the Agent wrote. */
  shared: z.boolean(),
});

export const PaginatedMemoryItemsSchema = z.object({
  items: z.array(MemoryItemSchema),
  page: z.number().int(),
  pageSize: z.number().int(),
  total: z.number().int(),
});

export type AgentMemoryState = z.infer<typeof AgentMemoryStateSchema>;
export type MemoryGrant = z.infer<typeof MemoryGrantSchema>;
export type MemoryItem = z.infer<typeof MemoryItemSchema>;
export type MemoryItemType = z.infer<typeof MemoryItemTypeSchema>;
export type PaginatedMemoryItems = z.infer<typeof PaginatedMemoryItemsSchema>;
