import { z } from "zod";

const JsonSchemaSchema = z.record(z.string(), z.unknown());

export const CommunicationPlatformSchema = z.object({
  key: z.string(),
  displayName: z.string(),
  schemaVersion: z.number().int().positive(),
  capabilities: z.array(z.string()),
  settingsSchema: JsonSchemaSchema,
  credentialsSchema: JsonSchemaSchema,
  setupHint: z.string().nullable().optional(),
});

export const CommunicationConnectionSchema = z.object({
  id: z.string().uuid(),
  agentId: z.string().uuid(),
  platformKey: z.string(),
  displayName: z.string(),
  enabled: z.boolean(),
  schemaVersion: z.number().int().positive(),
  settings: z.record(z.string(), z.unknown()),
  externalIdentity: z.string().nullable(),
  observedStatus: z.enum(["PENDING", "CONNECTING", "CONNECTED", "DEGRADED", "ERROR"]).nullable(),
  lastHealthAt: z.string().nullable(),
  lastErrorCode: z.string().nullable(),
  lastErrorMessage: z.string().nullable(),
  webhookUrl: z.string().url().nullable(),
  revision: z.number().int().positive(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export type CommunicationPlatform = z.infer<typeof CommunicationPlatformSchema>;
export type CommunicationConnection = z.infer<typeof CommunicationConnectionSchema>;

export type CreateCommunicationConnection = {
  agentId: string;
  platformKey: string;
  displayName: string;
  enabled: boolean;
  settings: Record<string, unknown>;
  credentials: Record<string, unknown>;
};

export type UpdateCommunicationConnection = {
  agentId: string;
  connectionId: string;
  revision: number;
  displayName?: string;
  enabled?: boolean;
  settings?: Record<string, unknown>;
  credentials?: Record<string, unknown>;
};
