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

export const ConversationMessageSchema = z.object({
  id: z.string().uuid(),
  direction: z.enum(["INBOUND", "OUTBOUND"]),
  threadId: z.string().nullable(),
  senderId: z.string().nullable(),
  senderName: z.string().nullable(),
  content: z.string(),
  occurredAt: z.string(),
});

export const ConversationChannelSchema = z.object({
  channelId: z.string(),
  channelName: z.string().nullable(),
});

export const ConversationsCursorSchema = z.object({
  beforeOccurredAt: z.string().nullable(),
  beforeId: z.string().uuid().nullable(),
});

export const ConversationMessagesPageSchema = z.object({
  messages: z.array(ConversationMessageSchema),
  hasMore: z.boolean(),
  nextCursor: ConversationsCursorSchema.nullable(),
});

export type Agent = z.infer<typeof AgentSchema>;
export type AgentHealth = z.infer<typeof AgentHealthSchema>;
export type AgentTemplateRead = z.infer<typeof AgentTemplateReadSchema>;
export type PaginatedAgents = z.infer<typeof PaginatedAgentsSchema>;
export type ConversationMessage = z.infer<typeof ConversationMessageSchema>;
export type ConversationChannel = z.infer<typeof ConversationChannelSchema>;
export type ConversationsCursor = z.infer<typeof ConversationsCursorSchema>;
export type ConversationMessagesPage = z.infer<typeof ConversationMessagesPageSchema>;
