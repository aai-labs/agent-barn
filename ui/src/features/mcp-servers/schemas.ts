import { z } from "zod";

/** `agent` is an Agent MCP Server: added for one Agent only. */
export const McpServerScopeSchema = z.enum(["all_agents", "selected_agents", "agent"]);
export const McpAuthTypeSchema = z.enum(["none", "bearer", "api_key", "oauth"]);
/** What an Agent's own credential for a token-based server can be: never an OAuth sign-in. */
export const McpStaticAuthTypeSchema = z.enum(["none", "bearer", "api_key"]);

/** An OAuth server's Organization sign-in; every member sees it. */
export const McpSignInSchema = z.object({
  status: z.enum(["signed_in", "needs_sign_in", "not_signed_in"]),
  signedInAt: z.string().nullable().optional(),
});

export const McpHeaderSchema = z.object({
  name: z.string(),
  secret: z.boolean(),
  value: z.string().nullable().optional(),
});

/**
 * An Organization MCP Server, or an Agent MCP Server (`agentId` set). `url`, `authType`,
 * `authHeaderName` and `headers` reach only those who manage it: Owners and Admins for an
 * Organization server, the Agent's editors for an Agent server. Everyone else gets them
 * null and empty, because some servers carry a key in the URL's path.
 */
export const McpServerSchema = z.object({
  id: z.string().uuid(),
  identifier: z.string(),
  name: z.string(),
  description: z.string().nullable(),
  scope: McpServerScopeSchema,
  enabled: z.boolean(),
  // Only Owners and Admins may turn it on for an Agent or give an Agent its own credential.
  restricted: z.boolean().default(false),
  toolInclude: z.array(z.string()).nullable(),
  toolExclude: z.array(z.string()).nullable(),
  attachmentCount: z.number().int().min(0),
  agentCount: z.number().int().min(0),
  url: z.string().nullable().optional(),
  authType: McpAuthTypeSchema.nullable().optional(),
  authHeaderName: z.string().nullable().optional(),
  headers: z.array(McpHeaderSchema).default([]),
  // Managers only, for an OAuth server: its client, and whether Agent Barn registered it.
  oauthClientId: z.string().nullable().optional(),
  oauthRegistered: z.boolean().nullable().optional(),
  // Null for a token-based server.
  signIn: McpSignInSchema.nullable().optional(),
  // An Agent server: its Agent.
  agentId: z.string().uuid().nullable().optional(),
  agentName: z.string().nullable().optional(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const McpToolSchema = z.object({
  name: z.string(),
  description: z.string().nullable(),
  openclawName: z.string(),
  truncated: z.boolean(),
  visible: z.boolean(),
});

export const McpServerProbeSchema = z.object({
  serverName: z.string().nullable(),
  serverVersion: z.string().nullable(),
  protocolVersion: z.string(),
  tools: z.array(McpToolSchema),
  warnings: z.array(z.string()),
});

export const AgentMcpServerSchema = z.object({
  id: z.string().uuid(),
  identifier: z.string(),
  name: z.string(),
  description: z.string().nullable(),
  scope: McpServerScopeSchema,
  enabled: z.boolean(),
  restricted: z.boolean().default(false),
  attached: z.boolean(),
  active: z.boolean(),
  authType: McpAuthTypeSchema.default("none"),
  // Which credential the gateway uses for this Agent: its own, the organization's, or none yet.
  credentialSource: z.enum(["agent", "organization", "missing"]).default("organization"),
  needsSignIn: z.boolean().default(false),
  hasAgentCredential: z.boolean().default(false),
  // The Agent's own token-based credential, never its token; secret header values come back null.
  agentCredential: z
    .object({
      authType: McpStaticAuthTypeSchema,
      authHeaderName: z.string().nullable().optional(),
      headers: z.array(McpHeaderSchema).default([]),
    })
    .nullable()
    .optional(),
});

export const AgentMcpServersSchema = z.object({
  servers: z.array(AgentMcpServerSchema),
  // This Agent's own servers.
  agentServers: z.array(McpServerSchema).default([]),
  // Whether the caller may change restricted servers for this Agent (Owners and Admins).
  canManageRestricted: z.boolean().default(false),
  pendingRestart: z.boolean(),
});

export type McpServerScope = z.infer<typeof McpServerScopeSchema>;
export type McpAuthType = z.infer<typeof McpAuthTypeSchema>;
export type McpStaticAuthType = z.infer<typeof McpStaticAuthTypeSchema>;
export type McpSignIn = z.infer<typeof McpSignInSchema>;
export type McpHeader = z.infer<typeof McpHeaderSchema>;
export type McpServer = z.infer<typeof McpServerSchema>;
export type McpTool = z.infer<typeof McpToolSchema>;
export type McpServerProbe = z.infer<typeof McpServerProbeSchema>;
export type AgentMcpServer = z.infer<typeof AgentMcpServerSchema>;
export type AgentMcpServers = z.infer<typeof AgentMcpServersSchema>;

/** What a create, update or probe sends. Keys are camelCase; the client sends snake_case. */
export type McpServerWrite = {
  name?: string;
  description?: string | null;
  url?: string;
  // Organization servers only; an Agent server has neither.
  scope?: Exclude<McpServerScope, "agent">;
  restricted?: boolean;
  enabled?: boolean;
  auth?: {
    type: McpAuthType;
    headerName?: string;
    token?: string;
    // OAuth only: an app the Admin registered with the server, for servers without automatic registration.
    clientId?: string;
    clientSecret?: string;
    scope?: string;
  };
  headers?: { name: string; value?: string; secret: boolean }[];
  toolInclude?: string[] | null;
  toolExclude?: string[] | null;
};

export const McpSignInStartSchema = z.object({
  authorizeUrl: z.string().url(),
});
export const McpSignInResultSchema = z.object({
  mcpServerId: z.string().uuid(),
  agentId: z.string().uuid().nullable(),
});

/** An Agent's own token and headers for a token-based server. */
export type AgentMcpCredentialWrite = {
  auth: { type: McpStaticAuthType; headerName?: string; token?: string };
  headers: { name: string; value?: string; secret: boolean }[];
};
