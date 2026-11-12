import { z } from "zod";

import { ResourceLimitsSchema } from "@/features/resource-usage/schemas";

export const SourceStateSchema = z.enum(["available", "forbidden", "unavailable", "not_configured"]);
export type SourceState = z.infer<typeof SourceStateSchema>;

export const EnvironmentSourceSchema = z.enum([
  "pods",
  "deployments",
  "stateful_sets",
  "volume_claims",
  "services",
  "cron_jobs",
  "jobs",
  "resource_quotas",
  "events",
  "prometheus",
]);
export type EnvironmentSource = z.infer<typeof EnvironmentSourceSchema>;

export const HealthLevelSchema = z.enum(["ok", "warning", "critical", "unknown"]);
export type HealthLevel = z.infer<typeof HealthLevelSchema>;

/**
 * An Agent a cluster resource belongs to, named from the database. With no live Agent
 * behind the id (an orphaned volume, say), only the id is known.
 */
export const AgentRefSchema = z.object({
  agentId: z.string().uuid(),
  agentName: z.string().nullable().default(null),
  organizationId: z.string().uuid().nullable().default(null),
  organizationName: z.string().nullable().default(null),
  status: z.string().nullable().default(null),
});
export type AgentRef = z.infer<typeof AgentRefSchema>;

export const CoreServiceSchema = z.object({
  name: z.string(),
  kind: z.string(),
  desiredReplicas: z.number().int(),
  readyReplicas: z.number().int(),
  level: HealthLevelSchema,
  /** The commit the service's image was built from. Deployments only. */
  buildSha: z.string().nullable().default(null),
  rollout: z.enum(["complete", "in_progress", "stuck"]).nullable().default(null),
  /** When the last rollout finished. Null while one is under way or stuck. */
  rolledOutAt: z.string().nullable().default(null),
});
export type CoreService = z.infer<typeof CoreServiceSchema>;

/** The build the platform runs: the one rolled out most recently. */
export const DeployedVersionSchema = z.object({
  buildSha: z.string(),
  rolledOutAt: z.string().nullable().default(null),
  mixed: z.boolean().default(false),
  /** The services on another build. */
  behind: z.array(z.string()).default([]),
});
export type DeployedVersion = z.infer<typeof DeployedVersionSchema>;

export const CronJobSchema = z.object({
  name: z.string(),
  schedule: z.string().nullable().default(null),
  state: z.enum(["ok", "failing", "stalled", "suspended"]),
  running: z.boolean().default(false),
  lastScheduledAt: z.string().nullable().default(null),
  lastSuccessfulAt: z.string().nullable().default(null),
  lastFailedAt: z.string().nullable().default(null),
});
export type CronJob = z.infer<typeof CronJobSchema>;

export const ScheduledBackupsSchema = z.object({
  enabled: z.boolean().default(false),
  intervalMinutes: z.number().int().default(0),
  failureWindowHours: z.number().int().default(24),
  failed: z
    .array(z.object({ agent: AgentRefSchema, failures: z.number().int(), lastFailedAt: z.string() }))
    .default([]),
  /** Running agents with no successful scheduled backup for two intervals or more. */
  overdue: z.array(z.object({ agent: AgentRefSchema, lastBackupAt: z.string().nullable().default(null) })).default([]),
});
export type ScheduledBackups = z.infer<typeof ScheduledBackupsSchema>;

export const FiringAlertSchema = z.object({
  name: z.string(),
  severity: z.string().nullable().default(null),
  agent: AgentRefSchema.nullable().default(null),
});
export type FiringAlert = z.infer<typeof FiringAlertSchema>;

export const CapacityLevelSchema = z.enum(["ok", "warning", "critical", "ceiling_out_of_date", "unknown"]);
export type CapacityLevel = z.infer<typeof CapacityLevelSchema>;

export const CapacityLineSchema = z.object({
  /** Named as the quota names it: `requests.storage`, `pods`, `limits.memory`, ... */
  resource: z.string(),
  unit: z.enum(["bytes", "cores", "count"]),
  /** `quota` is the cluster's own figure; `entered` is a ceiling an administrator typed in. */
  source: z.enum(["quota", "entered"]),
  /** Null when it could not be read: unknown, not zero. */
  used: z.number().nullable().default(null),
  hard: z.number().nullable().default(null),
  ratio: z.number().nullable().default(null),
  /** The highest `used` over the last `peakWindowHours`, for CPU, memory and pods. Null when unknown. */
  peak: z.number().nullable().default(null),
  peakRatio: z.number().nullable().default(null),
  level: CapacityLevelSchema,
});
export type CapacityLine = z.infer<typeof CapacityLineSchema>;

export const VolumeGroupSchema = z.enum([
  "infrastructure",
  "active_agents",
  "stopped_agents",
  "restore_points",
  "orphaned",
]);
export type VolumeGroup = z.infer<typeof VolumeGroupSchema>;

export const VolumeAllocationSchema = z.object({
  totalClaims: z.number().int().default(0),
  totalRequestedBytes: z.number().default(0),
  groups: z
    .array(z.object({ group: VolumeGroupSchema, claims: z.number().int(), requestedBytes: z.number() }))
    .default([]),
  /** Only the claims that need a look: orphaned, or not Bound. */
  attention: z
    .array(
      z.object({
        name: z.string(),
        group: VolumeGroupSchema,
        phase: z.string().nullable().default(null),
        requestedBytes: z.number().nullable().default(null),
        agent: AgentRefSchema.nullable().default(null),
        createdAt: z.string().nullable().default(null),
      }),
    )
    .default([]),
});
export type VolumeAllocation = z.infer<typeof VolumeAllocationSchema>;

export const PodIssueSchema = z.object({
  podName: z.string(),
  workloadName: z.string().nullable().default(null),
  kind: z.enum(["agent", "restore_point", "infrastructure"]),
  agent: AgentRefSchema.nullable().default(null),
  phase: z.string().nullable().default(null),
  ready: z.boolean(),
  unschedulable: z.boolean().default(false),
  /** Since the pod was created. Never reset, so a high count may be old news. */
  restartCount: z.number().int().default(0),
  /** Within the last `restartWindowDays`. Null when the restart history could not be read. */
  restartsInWindow: z.number().int().nullable().default(null),
  repeatedlyRestarting: z.boolean().default(false),
  /** A container ran out of memory within the last `restartWindowDays`. */
  oomKilled: z.boolean().default(false),
  waitingReason: z.string().nullable().default(null),
  terminationReason: z.string().nullable().default(null),
  lastRestartAt: z.string().nullable().default(null),
  createdAt: z.string().nullable().default(null),
});
export type PodIssue = z.infer<typeof PodIssueSchema>;

export const UnhealthyRuntimeSchema = z.object({
  agent: AgentRefSchema,
  podReady: z.boolean().nullable().default(null),
  /** False: never connected since the pod started. True: lost a connection it had. */
  everConnected: z.boolean().nullable().default(null),
});
export type UnhealthyRuntime = z.infer<typeof UnhealthyRuntimeSchema>;

export const FailedAgentSchema = z.object({
  agent: AgentRefSchema,
  code: z.string().nullable().default(null),
  summary: z.string().nullable().default(null),
  detail: z.string().nullable().default(null),
  updatedAt: z.string(),
});
export type FailedAgent = z.infer<typeof FailedAgentSchema>;

export const WarningEventSchema = z.object({
  reason: z.string(),
  objectKind: z.string().nullable().default(null),
  objectName: z.string().nullable().default(null),
  agent: AgentRefSchema.nullable().default(null),
  count: z.number().int().default(1),
  lastSeen: z.string().nullable().default(null),
  explanation: z.string(),
  detail: z.string().nullable().default(null),
});
export type WarningEvent = z.infer<typeof WarningEventSchema>;

export const EnvironmentHealthSchema = z.object({
  observedAt: z.string(),
  namespace: z.string(),
  level: HealthLevelSchema,
  peakWindowHours: z.number().int().default(24),
  restartWindowDays: z.number().int().default(7),
  sources: z.array(z.object({ source: EnvironmentSourceSchema, state: SourceStateSchema })).default([]),
  deployed: DeployedVersionSchema.nullable().default(null),
  ceilings: ResourceLimitsSchema,
  services: z.array(CoreServiceSchema).default([]),
  cronJobs: z.array(CronJobSchema).default([]),
  backups: ScheduledBackupsSchema.default({ enabled: false, intervalMinutes: 0, failureWindowHours: 24, failed: [], overdue: [] }),
  alerts: z.array(FiringAlertSchema).default([]),
  capacity: z.array(CapacityLineSchema).default([]),
  volumes: VolumeAllocationSchema,
  workloads: z.object({
    podsTotal: z.number().int().default(0),
    podsReady: z.number().int().default(0),
    issues: z.array(PodIssueSchema).default([]),
  }),
  unhealthyRuntimes: z.array(UnhealthyRuntimeSchema).default([]),
  failedAgents: z.array(FailedAgentSchema).default([]),
  events: z.array(WarningEventSchema).default([]),
});
export type EnvironmentHealth = z.infer<typeof EnvironmentHealthSchema>;
