import { z } from "zod";

export const AgentFileSyncStateSchema = z.enum([
  "not_connected",
  "turned_off",
  "setting_up",
  "throttled",
  "waiting_for_restart",
  "not_syncing",
  "synced",
]);

export type AgentFileSyncState = z.infer<typeof AgentFileSyncStateSchema>;

export const AgentFileSyncSchema = z.object({
  enabled: z.boolean(),
  state: AgentFileSyncStateSchema,
  provider: z.object({ key: z.string(), displayName: z.string() }).nullable(),
  folderUrl: z.string().nullable(),
  lastContactAt: z.string().nullable(),
  retryAt: z.string().nullable(),
});

export type AgentFileSync = z.infer<typeof AgentFileSyncSchema>;

export const AgentFileSyncSettingSchema = z.object({
  agentId: z.string(),
  enabled: z.boolean(),
});

export type AgentFileSyncSetting = z.infer<typeof AgentFileSyncSettingSchema>;
