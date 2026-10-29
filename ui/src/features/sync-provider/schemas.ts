import { z } from "zod";

export const SyncProviderConnectionSchema = z.object({
  status: z.enum(["pending", "active", "disconnected"]),
  locationName: z.string().nullable(),
  locationUrl: z.string().nullable(),
  folderWebUrl: z.string().nullable(),
  connectedAt: z.string().nullable(),
});

export type SyncProviderConnection = z.infer<typeof SyncProviderConnectionSchema>;

export const SyncProviderSchema = z.object({
  key: z.string(),
  displayName: z.string(),
  tagline: z.string(),
  folderHint: z.string(),
  connectHint: z.string().nullable(),
  locationNoun: z.string().nullable(),
  schemaVersion: z.number(),
  capabilities: z.array(z.string()),
  available: z.boolean(),
  approvalUrl: z.string().nullable(),
  connection: SyncProviderConnectionSchema.nullable(),
  canConnect: z.boolean(),
  blockedReason: z.string().nullable(),
});

export type SyncProvider = z.infer<typeof SyncProviderSchema>;

export const SyncLocationSchema = z.object({
  id: z.string(),
  name: z.string(),
  webUrl: z.string(),
});

export type SyncLocation = z.infer<typeof SyncLocationSchema>;

export const LOCATION_PICKER = "location_picker";
export const FILE_SYNC = "file_sync";
