import { z } from "zod";

import { AgentSizeOptionSchema } from "@/features/agent-sizes/schemas";

/**
 * One Agent on the Platform Agents page: identity, lifecycle and the size it runs on, as
 * Platform Oversight Data. Never its configuration.
 */
export const PlatformAgentSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  status: z.string(),
  agentType: z.string(),
  createdAt: z.string(),
  organizationId: z.string().uuid(),
  organizationName: z.string(),
  /** The stored size; null follows the platform default. */
  agentSizeId: z.string().uuid().nullable(),
  /** The size it would start on now. */
  agentSize: AgentSizeOptionSchema,
  /** A Platform Administrator set the size; its Organization cannot change it. */
  agentSizeSetByPlatform: z.boolean(),
  /** A running Agent's pod started on other resources; a restart applies the size. */
  pendingSize: z.boolean(),
});
export type PlatformAgent = z.infer<typeof PlatformAgentSchema>;

export const PaginatedPlatformAgentsSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(PlatformAgentSchema),
});
export type PaginatedPlatformAgents = z.infer<typeof PaginatedPlatformAgentsSchema>;
