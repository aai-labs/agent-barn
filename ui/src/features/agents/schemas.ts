import { z } from "zod";

import { OrganizationRoleSchema } from "@/features/organizations/schemas";
import { SkillScopeSchema } from "@/features/skills/schemas";

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
  // Optional: present on an Agent's actual assigned-skill reads, absent on the
  // narrower Template-required-skill snapshot this schema is also reused for.
  scope: SkillScopeSchema.optional(),
  requiredProviders: z.array(z.string()),
  toolsPointer: z.string().nullable(),
  required: z.boolean().default(false),
  createdAt: z.string(),
  updatedAt: z.string(),
  // The exact skill version this agent is pinned to (explicit, like templates).
  // Optional so template required-skill reads (which don't carry a pin) still parse.
  version: z.number().int().optional().default(1),
  updateAvailable: z.boolean().default(false),
  sourceSkillId: z.string().uuid().nullable().optional(),
  sourceSkillVersion: z.number().int().nullable().optional(),
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
  "agent.memory.read",
  "agent.memory.manage",
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

export const AgentProvisioningErrorSchema = z.object({
  code: z.string(),
  category: z.string(),
  summary: z.string(),
  detail: z.string().nullish(),
});

export const AgentSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  status: z.enum(["STOPPED", "RUNNING", "ERROR"]),
  agentType: z.enum(["openclaw", "hermes"]).default("openclaw"),
  organizationId: z.string().uuid(),
  templateKey: z.string(),
  templateVersion: z.number().int(),
  templatePinType: z.enum(["shared", "override"]).default("shared"),
  overrideVersion: z.number().int().nullable().optional(),
  // The stored value: empty means the Agent follows its organization's default.
  model: z.string(),
  // Resolved server-side so nothing here has to re-derive inheritance, and an
  // inheriting Agent can still name the model it will actually run.
  modelSource: z.enum(["default", "override"]).default("override"),
  effectiveModel: z.string().default(""),
  /** What the running pod actually started on; "" when the Agent is not running. */
  runningModel: z.string().default(""),
  /** Set only when a restart would move a running Agent onto a different model. */
  pendingModel: z.string().default(""),
  /** True when a running Agent's pod was built from older platform code or images. */
  updateAvailable: z.boolean().default(false),
  approvalMode: z.enum(["manual", "auto", "off"]).default("auto"),
  verboseMode: z.boolean().default(false),
  /** The memory group this Agent belongs to, or null for none. Managed via the
   *  memory-groups API; membership is the opt-in to shared memory. */
  memoryGroupId: z.string().uuid().nullable().default(null),
  lastError: AgentProvisioningErrorSchema.nullish(),
  secrets: z.array(AgentSecretReadSchema).optional(),
  skills: z.array(AgentAssignedSkillSchema).default([]),
  configuredPlatformKeys: z.array(z.string()).default([]),
  /** Platforms whose Connections this Agent's runtime runs itself; changing one requires a restart. */
  nativePlatformKeys: z.array(z.string()).default([]),
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
  connectionId: z.string().uuid(),
  direction: z.enum(["INBOUND", "OUTBOUND"]),
  threadId: z.string().nullable(),
  senderId: z.string().nullable(),
  senderName: z.string().nullable(),
  content: z.string(),
  occurredAt: z.string(),
});

export const ConversationChannelSchema = z.object({
  connectionId: z.string().uuid(),
  connectionName: z.string(),
  platformKey: z.string(),
  channelId: z.string(),
  channelName: z.string().nullable(),
  conversationType: z.enum(["CHANNEL", "DM"]),
});

export const WebChatApprovalSchema = z.object({
  approvalId: z.string(),
  command: z.string(),
  choices: z.array(z.string()),
  choiceLabels: z.record(z.string(), z.string()).default({}),
});

export const WebChatMessageSchema = z.object({
  id: z.string().uuid(),
  direction: z.enum(["INBOUND", "OUTBOUND"]),
  content: z.string(),
  occurredAt: z.string(),
  deliveryStatus: z.enum([
    "PENDING",
    "PROCESSING",
    "SUCCEEDED",
    "DEAD_LETTERED",
    "CANCELLED",
    "UNAVAILABLE",
  ]),
  cancelRequestedAt: z.string().nullable(),
  approval: WebChatApprovalSchema.nullish(),
  // Additive during a rolling API deployment; new responses include null when
  // no terminal error exists, while an older replica may omit the field.
  errorMessage: z.string().nullable().optional(),
});

export const WebChatThreadSchema = z.object({
  threadId: z.string(),
  title: z.string(),
  lastOccurredAt: z.string().nullable(),
  lastContent: z.string().nullable(),
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

export const AgentOverrideSourceTypeSchema = z.enum(["platform", "organization"]);

export const AgentOverrideAuthorSchema = z.object({
  userId: z.string().uuid().nullable(),
  email: z.string().nullable(),
  fullName: z.string().nullable(),
});

export const AgentOverrideRequiredSkillSchema = AgentAssignedSkillSchema.extend({
  groupKey: z.string().nullable().optional().default(null),
});

const AgentConfigurationSnapshotSchema = z.object({
  id: z.string().uuid(),
  agentId: z.string().uuid(),
  version: z.number().int().nullable(),
  templateKey: z.string(),
  templateName: z.string(),
  description: z.string().nullable(),
  soulMd: z.string(),
  identityMd: z.string(),
  userMd: z.string(),
  toolsMd: z.string(),
  agentsMd: z.string(),
  bootMd: z.string(),
  bootstrapMd: z.string(),
  heartbeatMd: z.string(),
  sourceType: AgentOverrideSourceTypeSchema,
  sourceTemplateKey: z.string(),
  sourceTemplateVersion: z.number().int(),
  sourcePlatformTemplateId: z.string().uuid().nullable(),
  sourceAgentTemplateId: z.string().uuid().nullable(),
  createdByUserId: z.string().uuid().nullable(),
  author: AgentOverrideAuthorSchema.nullable().optional(),
  requiredSkills: z.array(AgentOverrideRequiredSkillSchema).default([]),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const AgentConfigurationVersionSchema = AgentConfigurationSnapshotSchema.extend({
  state: z.enum(["active", "published"]),
  pinType: z.enum(["shared", "override"]).default("shared"),
  templateSource: z.string().nullable().optional(),
});

export const AgentOverrideDraftSchema = AgentConfigurationSnapshotSchema.extend({
  version: z.number().int().nullable(),
  state: z.literal("draft"),
  pinType: z.literal("override"),
});

export const AgentOverrideVersionSchema = AgentConfigurationSnapshotSchema.extend({
  version: z.number().int(),
  state: z.literal("published"),
  pinType: z.literal("override"),
});

export const AgentConfigurationSchema = z.object({
  agentId: z.string().uuid(),
  active: AgentConfigurationVersionSchema,
  draft: AgentOverrideDraftSchema.nullable(),
  sourceUpdate: AgentConfigurationVersionSchema.nullable().optional(),
  sharedVersions: z.array(AgentConfigurationVersionSchema).default([]),
  overrideVersions: z.array(AgentOverrideVersionSchema).default([]),
});


export type CommandApprovalMode = "manual" | "auto" | "off";
export type AgentPermissionKey = z.infer<typeof AgentPermissionKeySchema>;
export type Agent = z.infer<typeof AgentSchema>;
export type AgentProvisioningError = z.infer<typeof AgentProvisioningErrorSchema>;
export type AgentAssignedSkill = z.infer<typeof AgentAssignedSkillSchema>;
export type TemplateRequiredSkill = z.infer<typeof TemplateRequiredSkillSchema>;
export type AgentHealth = z.infer<typeof AgentHealthSchema>;
export type AgentTemplateRead = z.infer<typeof AgentTemplateReadSchema>;
export const AgentNameSuggestionSchema = z.object({ firstName: z.string().min(1) });
export type AgentNameSuggestion = z.infer<typeof AgentNameSuggestionSchema>;

export type TemplateSource = AgentTemplateRead["templateSource"];
export type PaginatedTemplates = z.infer<typeof PaginatedTemplatesSchema>;
export type PaginatedAgents = z.infer<typeof PaginatedAgentsSchema>;
export type AgentOverrideAuthor = z.infer<typeof AgentOverrideAuthorSchema>;
export type AgentOverrideRequiredSkill = z.infer<typeof AgentOverrideRequiredSkillSchema>;
export type AgentConfigurationVersion = z.infer<typeof AgentConfigurationVersionSchema>;
export type AgentOverrideDraft = z.infer<typeof AgentOverrideDraftSchema>;
export type AgentOverrideVersion = z.infer<typeof AgentOverrideVersionSchema>;
export type AgentConfiguration = z.infer<typeof AgentConfigurationSchema>;
export type WebChatMessage = z.infer<typeof WebChatMessageSchema>;
export type WebChatApproval = z.infer<typeof WebChatApprovalSchema>;
export type WebChatThread = z.infer<typeof WebChatThreadSchema>;
export type ConversationMessage = z.infer<typeof ConversationMessageSchema>;
export type ConversationChannel = z.infer<typeof ConversationChannelSchema>;
export type ConversationsCursor = z.infer<typeof ConversationsCursorSchema>;
export type ConversationMessagesPage = z.infer<typeof ConversationMessagesPageSchema>;
export type ConversationThread = z.infer<typeof ConversationThreadSchema>;
export type ConversationThreadsPage = z.infer<typeof ConversationThreadsPageSchema>;
export type ToolCall = z.infer<typeof ToolCallSchema>;
export type PaginatedToolCalls = z.infer<typeof PaginatedToolCallsSchema>;
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

// Memory is stored per (observer, observed) peer pair: the same Agent holds a
// separate view of each person it talks to, plus a model of itself. The pair is
// surfaced rather than flattened, because collapsing it would misrepresent whose
// memory an item actually is.
export const AgentMemoryItemSchema = z.object({
  id: z.string(),
  content: z.string(),
  observer: z.string(),
  observed: z.string(),
  level: z.string(),
  createdAt: z.string().nullable().optional(),
  // Set only for a memory shared in from another pool (group). The id, not the
  // name — the client resolves the name from its groups list. `sharedAt` is when
  // it was shared; a null group id with a set sharedAt means the source group is gone.
  sharedAt: z.string().nullable().optional(),
  sharedFromGroupId: z.string().uuid().nullable().optional(),
});

// One peer the memory can be filtered to, with its real count. `peer` is the id
// sent back to filter; `label` is what the chip shows.
export const AgentMemoryFacetSchema = z.object({
  peer: z.string(),
  label: z.string(),
  // The bare display name behind `label` ("you", an agent's name, or the raw
  // peer). The list keys its per-row "· about X" label off this so an agent peer
  // never shows as a raw id there either.
  name: z.string(),
  count: z.number().int(),
  isSelf: z.boolean(),
});

export const AgentMemoryPageSchema = z.object({
  items: z.array(AgentMemoryItemSchema),
  total: z.number().int(),
  page: z.number().int(),
  size: z.number().int(),
  // Present only on the unfiltered view; the chips it drives describe the whole
  // workspace. Undeclared fields are stripped by zod, so this must be listed.
  facets: z.array(AgentMemoryFacetSchema).default([]),
});

export type AgentMemoryItem = z.infer<typeof AgentMemoryItemSchema>;
export type AgentMemoryFacet = z.infer<typeof AgentMemoryFacetSchema>;
export type AgentMemoryPage = z.infer<typeof AgentMemoryPageSchema>;

export const RestorePointStatusSchema = z.enum([
  "PENDING",
  "CAPTURING",
  "RESTORING",
  "READY",
  "FAILED",
  "DELETING",
]);

export const RestorePointOriginSchema = z.enum([
  "MANUAL",
  "PRE_RESTORE",
  "PRE_RESET",
  "PRE_UPGRADE",
]);

export const RestorePointSkillSchema = z.object({
  skillId: z.string().uuid(),
  name: z.string(),
  pinnedVersion: z.number().int(),
});

// Versioned free-form JSON: a row captured before a field existed omits it, so
// every field defaults rather than failing the parse.
export const RestorePointConfigManifestSchema = z.object({
  version: z.number().int().default(1),
  agentType: z.string().default(""),
  templateKey: z.string().default(""),
  templateVersion: z.number().int().default(0),
  templateSelectionType: z.enum(["platform", "organization", "override", ""]).catch(""),
  overrideVersion: z.number().int().nullish().default(null),
  model: z.string().default(""),
  effectiveModel: z.string().default(""),
  approvalMode: z.string().default(""),
  verboseMode: z.boolean().default(false),
  skills: z.array(RestorePointSkillSchema).default([]),
});

export const RestorePointSchema = z.object({
  id: z.string().uuid(),
  agentId: z.string().uuid(),
  label: z.string().nullable(),
  status: RestorePointStatusSchema,
  origin: RestorePointOriginSchema,
  agentType: z.string(),
  archiveBytes: z.number().int().nullable(),
  fileCount: z.number().int().nullable(),
  failureReason: z.string().nullable(),
  // True while a confirmed restore still owes the Agent its recorded configuration.
  reapplyConfiguration: z.boolean().default(false),
  // Set when the volume came back but the configuration did not.
  configurationError: z.string().nullable().default(null),
  configManifest: RestorePointConfigManifestSchema,
  createdAt: z.string(),
  capturedAt: z.string().nullable(),
});

export const PaginatedRestorePointsSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(RestorePointSchema),
  // The cap counts neither system-created backups nor failed captures; total counts both.
  cap: z.number().int().min(1),
  manualCount: z.number().int().min(0),
});

export type RestorePointStatus = z.infer<typeof RestorePointStatusSchema>;
export type RestorePointOrigin = z.infer<typeof RestorePointOriginSchema>;
export type RestorePointSkill = z.infer<typeof RestorePointSkillSchema>;
export type RestorePointConfigManifest = z.infer<typeof RestorePointConfigManifestSchema>;
export type RestorePoint = z.infer<typeof RestorePointSchema>;
export type PaginatedRestorePoints = z.infer<typeof PaginatedRestorePointsSchema>;

// --- Activity ---------------------------------------------------------------
//
// What the Agent has been doing, read off its billed model calls. A *wake* is a
// burst of calls close together — the unit of work a person recognises — and its
// trigger says whether anybody asked for it.

export const ActivityTriggerSchema = z.enum(["user", "background"]);
export const ActivityGranularitySchema = z.enum(["minute", "hour", "day", "week"]);

export const ActivityTotalsSchema = z.object({
  calls: z.number().int().default(0),
  wakes: z.number().int().default(0),
  spend: z.number().default(0),
  promptTokens: z.number().int().default(0),
  completionTokens: z.number().int().default(0),
});

export const PromptTokenDistributionSchema = z.object({
  avg: z.number().default(0),
  median: z.number().int().default(0),
  p95: z.number().int().default(0),
  max: z.number().int().default(0),
});

export const ActivityTriggerBreakdownSchema = z.object({
  trigger: ActivityTriggerSchema,
  wakes: z.number().int().default(0),
  calls: z.number().int().default(0),
  spend: z.number().default(0),
  promptTokens: z.number().int().default(0),
});

export const ActivityBucketSchema = z.object({
  bucket: z.string(),
  calls: z.number().int().default(0),
  promptTokens: z.number().int().default(0),
  completionTokens: z.number().int().default(0),
  spend: z.number().default(0),
});

export const AgentActivitySummarySchema = z.object({
  agentId: z.string().uuid(),
  period: z.string().nullable().default(null),
  fromDate: z.string(),
  toDate: z.string(),
  granularity: ActivityGranularitySchema,
  lastCallAt: z.string().nullable().default(null),
  totals: ActivityTotalsSchema,
  promptTokensPerCall: PromptTokenDistributionSchema,
  byTrigger: z.array(ActivityTriggerBreakdownSchema).default([]),
  byBucket: z.array(ActivityBucketSchema).default([]),
  wakeCadenceSeconds: z.number().int().nullable().default(null),
});

export const AgentWakeSchema = z.object({
  startedAt: z.string(),
  endedAt: z.string(),
  trigger: ActivityTriggerSchema,
  calls: z.number().int(),
  spend: z.number(),
  promptTokens: z.number().int(),
  completionTokens: z.number().int(),
  minPromptTokens: z.number().int(),
  maxPromptTokens: z.number().int(),
  models: z.array(z.string()).default([]),
});

export const AgentActivityCallSchema = z.object({
  requestId: z.string(),
  occurredAt: z.string(),
  model: z.string(),
  status: z.string(),
  spend: z.number(),
  promptTokens: z.number().int(),
  completionTokens: z.number().int(),
  requestDurationMs: z.number().int().nullable().default(null),
});

export const PaginatedAgentWakesSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(AgentWakeSchema),
});

export const PaginatedAgentActivityCallsSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(AgentActivityCallSchema),
});

export type ActivityTrigger = z.infer<typeof ActivityTriggerSchema>;
export type ActivityTriggerBreakdown = z.infer<typeof ActivityTriggerBreakdownSchema>;
export type ActivityBucket = z.infer<typeof ActivityBucketSchema>;
export type AgentActivitySummary = z.infer<typeof AgentActivitySummarySchema>;
export type AgentWake = z.infer<typeof AgentWakeSchema>;
export type AgentActivityCall = z.infer<typeof AgentActivityCallSchema>;
export type PaginatedAgentWakes = z.infer<typeof PaginatedAgentWakesSchema>;
export type PaginatedAgentActivityCalls = z.infer<typeof PaginatedAgentActivityCallsSchema>;

export const AgentRuntimeDiagnosticsSchema = z.object({
  observedAt: z.string(),
  available: z.boolean(),
  podCreatedAt: z.string().nullable(),
  restartCount: z.number().int(),
  ready: z.boolean(),
  waitingReason: z.string().nullable(),
  terminationReason: z.string().nullable(),
  exitCode: z.number().int().nullable(),
  finishedAt: z.string().nullable(),
  currentLogs: z.array(z.string()),
  previousLogs: z.array(z.string()),
  currentLogsAvailable: z.boolean(),
  previousLogsAvailable: z.boolean(),
});
export type AgentRuntimeDiagnostics = z.infer<typeof AgentRuntimeDiagnosticsSchema>;
