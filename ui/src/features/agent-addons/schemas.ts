import { z } from "zod";

export const AgentAddonKindSchema = z.enum(["pip", "npm", "git", "binary", "command"]);
export type AgentAddonKind = z.infer<typeof AgentAddonKindSchema>;

export const AgentAddonStateSchema = z.enum(["PENDING", "APPROVED", "REJECTED", "WITHDRAWN", "REVOKED"]);
export type AgentAddonState = z.infer<typeof AgentAddonStateSchema>;

/** The pin, by kind: version (pip, npm), url and commit (git), url and sha256 (binary), or command. */
export const AgentAddonSpecSchema = z.object({
  version: z.string().nullish(),
  url: z.string().nullish(),
  commit: z.string().nullish(),
  sha256: z.string().nullish(),
  command: z.string().nullish(),
});
export type AgentAddonSpec = z.infer<typeof AgentAddonSpecSchema>;

const PersonSchema = z.object({ fullName: z.string().nullable(), email: z.string() });

export const AgentAddonSchema = z.object({
  id: z.string().uuid(),
  agentId: z.string().uuid(),
  kind: AgentAddonKindSchema,
  name: z.string(),
  spec: AgentAddonSpecSchema,
  /** Why the Organization asked for it. */
  reason: z.string(),
  state: AgentAddonStateSchema,
  rejectionReason: z.string().nullable(),
  requestedBy: PersonSchema.nullable(),
  decidedAt: z.string().nullable(),
  createdAt: z.string(),
  updatedAt: z.string(),
});
export type AgentAddon = z.infer<typeof AgentAddonSchema>;

export const AgentAddonsSchema = z.object({
  items: z.array(AgentAddonSchema),
  /** The kinds this Agent's runtime offers. */
  availableKinds: z.array(AgentAddonKindSchema),
  /** How many Pending and Approved add-ons it may have at once. */
  maxActive: z.number().int(),
});
export type AgentAddons = z.infer<typeof AgentAddonsSchema>;

/** A request as the Platform requests page reads it: Platform Oversight Data plus the request itself. */
export const PlatformAgentAddonSchema = z.object({
  id: z.string().uuid(),
  organizationId: z.string().uuid(),
  organizationName: z.string(),
  agentId: z.string().uuid(),
  agentName: z.string(),
  agentType: z.string(),
  agentDeleted: z.boolean(),
  kind: AgentAddonKindSchema,
  name: z.string(),
  spec: AgentAddonSpecSchema,
  reason: z.string(),
  state: AgentAddonStateSchema,
  rejectionReason: z.string().nullable(),
  requestedBy: PersonSchema.nullable(),
  decidedBy: PersonSchema.nullable(),
  createdAt: z.string(),
  decidedAt: z.string().nullable(),
  updatedAt: z.string(),
});
export type PlatformAgentAddon = z.infer<typeof PlatformAgentAddonSchema>;

export const PaginatedPlatformAgentAddonsSchema = z.object({
  page: z.number().int().min(1),
  pageSize: z.number().int().min(1),
  total: z.number().int().min(0),
  items: z.array(PlatformAgentAddonSchema),
});
export type PaginatedPlatformAgentAddons = z.infer<typeof PaginatedPlatformAgentAddonsSchema>;

/** What the Request dialog sends: the kind, its own fields, and why. */
export type AgentAddonRequest =
  | { kind: "pip" | "npm"; name: string; version: string; reason: string }
  | { kind: "git"; name: string; url: string; commit: string; reason: string }
  | { kind: "binary"; name: string; url: string; sha256: string; reason: string }
  | { kind: "command"; name: string; command: string; reason: string };
