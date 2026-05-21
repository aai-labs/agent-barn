import { z } from "zod";

export const AgentSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  status: z.enum(["STOPPED", "RUNNING", "ERROR"]),
  organizationId: z.string().uuid(),
  templateId: z.string().uuid(),
  templateVersion: z.number().int(),
  model: z.string(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const AgentTemplateReadSchema = z.object({
  id: z.string().uuid(),
  organizationId: z.string().uuid(),
  version: z.number().int(),
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
});

export const PaginatedAgentsSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(AgentSchema),
});

export const AgentHealthSchema = z.object({
  status: z.enum(["ok", "error", "starting"]),
  reason: z.string().optional(),
});

export type Agent = z.infer<typeof AgentSchema>;
export type AgentHealth = z.infer<typeof AgentHealthSchema>;
export type AgentTemplateRead = z.infer<typeof AgentTemplateReadSchema>;
export type PaginatedAgents = z.infer<typeof PaginatedAgentsSchema>;
