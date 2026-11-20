import { z } from "zod";

export const SshServerSchema = z.object({
  name: z.string(),
  hostname: z.string(),
  port: z.number().int(),
  username: z.string(),
  hostKeys: z.array(z.string()),
});
export const SshCredentialSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  publicKey: z.string(),
  fingerprint: z.string(),
  algorithm: z.string(),
  origin: z.string(),
  enabled: z.boolean(),
  mode: z.enum(["restricted", "unrestricted"]),
  servers: z.array(SshServerSchema),
  revision: z.number().int(),
  createdAt: z.string(),
  agentCount: z.number().int(),
});
export const SshCredentialListSchema = z.object({
  items: z.array(SshCredentialSchema),
  total: z.number().int(),
});
export const SshAssignmentsSchema = z.object({
  credentials: z.array(SshCredentialSchema),
  revision: z.number().int(),
  appliedIds: z.array(z.string()),
  pendingApply: z.boolean(),
  enabled: z.boolean(),
  allowedActions: z.array(z.string()),
});
export type SshCredential = z.infer<typeof SshCredentialSchema>;
export type SshServer = z.infer<typeof SshServerSchema>;
export type SshAssignments = z.infer<typeof SshAssignmentsSchema>;

export type SshCredentialList = z.infer<typeof SshCredentialListSchema>;
