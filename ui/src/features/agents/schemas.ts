import { z } from "zod";

import { OrganizationRoleSchema } from "@/features/organizations/schemas";

export const AgentSlackConfigSchema = z.object({
  channelIds: z.array(z.string()),
  dmUserIds: z.array(z.string()),
  groupPolicy: z.enum(["open", "allowlist"]),
  dmPolicy: z.enum(["off", "open", "allowlist"]),
  verboseMode: z.boolean().default(true),
  botDisplayName: z.string().nullable().optional(),
});

export const AgentTeamsConfigSchema = z.object({
  tenantId: z.string(),
});

export const AgentTelegramConfigSchema = z.object({
  allowedUserIds: z.array(z.string()),
  allowedChatIds: z.array(z.string()),
  groupPolicy: z.enum(["open", "allowlist"]),
  dmPolicy: z.enum(["off", "open", "allowlist"]),
  botUsername: z.string().nullable().optional(),
});

export const AgentSecretReadSchema = z.object({
  provider: z.string(),
  secretName: z.string(),
  sharedCredentialId: z.string().uuid().nullable().optional(),
  sharedCredentialName: z.string().nullable().optional(),
});

export const IntegrationValidationResultSchema = z.object({
  validationStatus: z.enum(["valid", "warning", "invalid"]),
  validationIdentity: z.string().nullable().optional(),
  validationError: z.string().nullable().optional(),
  missingScopes: z.array(z.string()).default([]),
});

export type AgentSecretRead = z.infer<typeof AgentSecretReadSchema>;
export type IntegrationValidationResult = z.infer<typeof IntegrationValidationResultSchema>;

export const AgentAssignedSkillSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  source: z.string(),
  requiredProviders: z.array(z.string()),
  toolsPointer: z.string().nullable(),
  required: z.boolean().default(false),
  createdAt: z.string(),
  updatedAt: z.string(),
});

// A template's required skill. groupKey is null for a standalone
// (AND-required) skill; skills sharing the same non-null groupKey form an
// "at least one of" requirement group (e.g. GitHub OR Bitbucket) — the user
// must pick one at hire time, and can't drop below one member thereafter.
export const TemplateRequiredSkillSchema = AgentAssignedSkillSchema.extend({
  groupKey: z.string().nullable().optional().default(null),
});

export const AgentPermissionKeySchema = z.enum([
  "agent.read",
  "agent.update",
  "agent.delete",
  "agent.lifecycle.manage",
  "agent.access.manage",
  "agent.secret.manage",
  "activity.read",
  "cost.read",
]);

export const AgentAccessRoleReadSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  permissions: z.array(AgentPermissionKeySchema),
  isLocked: z.boolean(),
});

export const AgentAccessCandidateReadSchema = z.object({
  userId: z.string().uuid(),
  email: z.string(),
  fullName: z.string().nullable(),
  organizationRole: OrganizationRoleSchema,
  isPending: z.boolean(),
  isCreator: z.boolean(),
});

export const AgentAccessMemberReadSchema = AgentAccessCandidateReadSchema.extend({
  accessRole: AgentAccessRoleReadSchema,
});

export const AgentGeneralAccessReadSchema = z.object({
  role: AgentAccessRoleReadSchema.nullable(),
});

export const AgentAccessSettingsReadSchema = z.object({
  generalAccess: AgentGeneralAccessReadSchema,
  assignments: z.array(AgentAccessMemberReadSchema),
});

export const AgentSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  status: z.enum(["STOPPED", "RUNNING", "ERROR"]),
  platform: z.enum(["slack", "teams", "telegram"]),
  agentType: z.enum(["openclaw", "hermes"]).default("openclaw"),
  organizationId: z.string().uuid(),
  templateKey: z.string(),
  templateVersion: z.number().int(),
  model: z.string(),
  approvalMode: z.enum(["manual", "auto", "off"]).default("auto"),
  slackConfig: AgentSlackConfigSchema.nullable().optional(),
  teamsConfig: AgentTeamsConfigSchema.nullable().optional(),
  telegramConfig: AgentTelegramConfigSchema.nullable().optional(),
  secrets: z.array(AgentSecretReadSchema).optional(),
  skills: z.array(AgentAssignedSkillSchema).default([]),
  webhookUrl: z.string().nullable().optional(),
  allowedActions: z.array(AgentPermissionKeySchema).default([]),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const AgentTemplateReadSchema = z.object({
  id: z.string().uuid(),
  organizationId: z.string().uuid().nullable(),
  templateKey: z.string(),
  templateName: z.string(),
  templateSource: z.enum(["pre-defined", "custom"]),
  forkedFromPlatformTemplateId: z.string().uuid().nullable().optional(),
  forkBaselinePlatformTemplateId: z.string().uuid().nullable().optional(),
  forkBaselinePlatformVersion: z.number().int().nullable().optional(),
  platformUpdateAvailable: z.boolean().default(false),
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
  requiredSkills: z.array(TemplateRequiredSkillSchema).default([]),
  inUse: z.boolean().default(false),
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

export const AgentLogsReadSchema = z.object({
  lines: z.array(z.string()),
  source: z.enum(["live", "snapshot"]),
  hasSnapshots: z.boolean().optional().default(false),
  snapshotId: z.string().uuid().nullable().optional(),
  sessionStartedAt: z.string().nullable().optional(),
  sessionEndedAt: z.string().nullable().optional(),
});

export const AgentLogHistoryReadSchema = z.object({
  lines: z.array(z.string()),
  hasMore: z.boolean(),
  sessionEndedAt: z.string().nullable().optional(),
  nextSnapshotId: z.string().uuid().nullable().optional(),
});


export type CommandApprovalMode = "manual" | "auto" | "off";
export type AgentPermissionKey = z.infer<typeof AgentPermissionKeySchema>;
export type Agent = z.infer<typeof AgentSchema>;
export type AgentAssignedSkill = z.infer<typeof AgentAssignedSkillSchema>;
export type TemplateRequiredSkill = z.infer<typeof TemplateRequiredSkillSchema>;
export type AgentSlackConfig = z.infer<typeof AgentSlackConfigSchema>;
export type AgentTeamsConfig = z.infer<typeof AgentTeamsConfigSchema>;
export type AgentTelegramConfig = z.infer<typeof AgentTelegramConfigSchema>;
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
export type AgentLogHistoryRead = z.infer<typeof AgentLogHistoryReadSchema>;
export type AgentLogsRead = z.infer<typeof AgentLogsReadSchema>;
export type AgentAccessRoleRead = z.infer<typeof AgentAccessRoleReadSchema>;
export type AgentAccessMemberRead = z.infer<typeof AgentAccessMemberReadSchema>;
export type AgentGeneralAccessRead = z.infer<typeof AgentGeneralAccessReadSchema>;
export type AgentAccessSettingsRead = z.infer<typeof AgentAccessSettingsReadSchema>;

export const AgentAccessSettingsAssignmentUpdateSchema = z.object({
  userId: z.string().uuid(),
  accessRoleId: z.string().uuid(),
});

export const AgentAccessSettingsUpdateSchema = z.object({
  generalAccessRoleId: z.string().uuid().nullable(),
  assignments: z.array(AgentAccessSettingsAssignmentUpdateSchema),
});

export type AgentAccessSettingsAssignmentUpdate = z.infer<
  typeof AgentAccessSettingsAssignmentUpdateSchema
>;
export type AgentAccessSettingsUpdate = z.infer<typeof AgentAccessSettingsUpdateSchema>;
