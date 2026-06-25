import { z } from "zod";

export const AgentSlackConfigSchema = z.object({
  channelIds: z.array(z.string()),
  dmUserIds: z.array(z.string()),
  groupPolicy: z.enum(["open", "allowlist"]),
  dmPolicy: z.enum(["off", "open", "allowlist"]),
});

export const AgentTeamsConfigSchema = z.object({
  tenantId: z.string(),
});

export const AgentSecretReadSchema = z.object({
  provider: z.string(),
  secretName: z.string(),
});

export const AgentAssignedSkillSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  source: z.string(),
  requiredProviders: z.array(z.string()),
  toolsPointer: z.string().nullable(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const AgentSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  status: z.enum(["STOPPED", "RUNNING", "ERROR"]),
  platform: z.enum(["slack", "teams"]),
  agentType: z.enum(["openclaw", "hermes"]).default("openclaw"),
  organizationId: z.string().uuid(),
  templateSlug: z.string(),
  templateVersion: z.number().int(),
  model: z.string(),
  slackConfig: AgentSlackConfigSchema.nullable().optional(),
  teamsConfig: AgentTeamsConfigSchema.nullable().optional(),
  secrets: z.array(AgentSecretReadSchema).optional(),
  skills: z.array(AgentAssignedSkillSchema).default([]),
  webhookUrl: z.string().nullable().optional(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const AgentTemplateReadSchema = z.object({
  id: z.string().uuid(),
  organizationId: z.string().uuid(),
  templateSlug: z.string(),
  templateName: z.string(),
  templateSource: z.enum(["pre-defined", "custom"]),
  version: z.number().int(),
  description: z.string().nullable().optional(),
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

export const PaginatedTemplatesSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(AgentTemplateReadSchema),
});

export const TemplateVersionsSchema = z.array(AgentTemplateReadSchema);

export const PaginatedAgentsSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(AgentSchema),
});

export const AgentHealthSchema = z.object({
  status: z.enum(["ok", "error", "starting", "initializing", "crashed"]),
  reason: z.string().nullish(),
});

export const ToolCallStatusSchema = z.enum(["PENDING", "SUCCESS", "ERROR"]);

export const ToolCallSchema = z.object({
  id: z.string().uuid(),
  agentId: z.string().uuid(),
  sessionId: z.string(),
  toolName: z.string(),
  arguments: z.record(z.string(), z.unknown()),
  result: z.unknown().nullable(),
  status: ToolCallStatusSchema,
  occurredAt: z.string(),
  completedAt: z.string().nullable(),
  durationMs: z.number().int().nullable(),
});

export const PaginatedToolCallsSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(ToolCallSchema),
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
  conversationType: z.enum(["CHANNEL", "DM"]),
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

export const ConversationThreadSchema = z.object({
  root: ConversationMessageSchema,
  replies: z.array(ConversationMessageSchema),
});

export const ConversationThreadsPageSchema = z.object({
  threads: z.array(ConversationThreadSchema),
  hasMore: z.boolean(),
  nextCursor: ConversationsCursorSchema.nullable(),
});

export const SlackChannelSchema = z.object({
  id: z.string(),
  name: z.string(),
  isPrivate: z.boolean().optional(),
});

export const SlackUserSchema = z.object({
  id: z.string(),
  name: z.string(),
  realName: z.string(),
  displayName: z.string(),
});

export const ModelOptionSchema = z.object({
  value: z.string(),
  label: z.string(),
  contextLength: z.number().nullish(),
  pricing: z.unknown().nullish(),
  isDefault: z.boolean().optional(),
});

export type Agent = z.infer<typeof AgentSchema>;
export type AgentAssignedSkill = z.infer<typeof AgentAssignedSkillSchema>;
export type AgentSlackConfig = z.infer<typeof AgentSlackConfigSchema>;
export type AgentTeamsConfig = z.infer<typeof AgentTeamsConfigSchema>;
export type AgentHealth = z.infer<typeof AgentHealthSchema>;
export type AgentTemplateRead = z.infer<typeof AgentTemplateReadSchema>;
export type TemplateSource = AgentTemplateRead["templateSource"];
export type PaginatedTemplates = z.infer<typeof PaginatedTemplatesSchema>;
export type PaginatedAgents = z.infer<typeof PaginatedAgentsSchema>;
export type ConversationMessage = z.infer<typeof ConversationMessageSchema>;
export type ConversationChannel = z.infer<typeof ConversationChannelSchema>;
export type ConversationsCursor = z.infer<typeof ConversationsCursorSchema>;
export type ConversationMessagesPage = z.infer<typeof ConversationMessagesPageSchema>;
export type ConversationThread = z.infer<typeof ConversationThreadSchema>;
export type ConversationThreadsPage = z.infer<typeof ConversationThreadsPageSchema>;
export type ToolCall = z.infer<typeof ToolCallSchema>;
export type PaginatedToolCalls = z.infer<typeof PaginatedToolCallsSchema>;
export type SlackChannel = z.infer<typeof SlackChannelSchema>;
export type SlackUser = z.infer<typeof SlackUserSchema>;
export type ModelOption = z.infer<typeof ModelOptionSchema>;
