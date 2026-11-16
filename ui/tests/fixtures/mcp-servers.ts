import { TEST_ORG_ID } from "../constants";

export const MCP_SERVER_ID = "6a6a6a6a-1111-4111-8111-111111111111";
export const MCP_ALL_AGENTS_ID = "6a6a6a6a-2222-4222-8222-222222222222";
export const MCP_OAUTH_ID = "6a6a6a6a-4444-4444-8444-444444444444";

/** How the API returns a server to an Owner or Admin. */
export const mockMcpServer = {
  id: MCP_SERVER_ID,
  identifier: "deepwiki",
  name: "DeepWiki",
  description: "Read GitHub repository wikis",
  scope: "selected_agents",
  enabled: true,
  tool_include: null,
  tool_exclude: ["ask_wiki_question"],
  attachment_count: 1,
  agent_count: 1,
  url: "https://mcp.deepwiki.com/k/abc123/mcp",
  auth_type: "bearer",
  auth_header_name: null,
  headers: [{ name: "X-Signing", secret: true, value: null }],
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

/** An OAuth server nobody has signed in to yet, as an Owner or Admin receives it. */
export const mockOAuthMcpServer = {
  ...mockMcpServer,
  id: MCP_OAUTH_ID,
  identifier: "notion",
  name: "Notion",
  description: "Workspace pages",
  tool_exclude: null,
  url: "https://mcp.notion.com/mcp",
  auth_type: "oauth",
  headers: [],
  oauth_client_id: "registered-client",
  oauth_registered: true,
  sign_in: { status: "not_signed_in", signed_in_at: null },
};

/** The same server as a Member receives it: no URL, no authentication. */
export const mockMcpServerForMember = {
  ...mockMcpServer,
  url: null,
  auth_type: null,
  auth_header_name: null,
  headers: [],
};

export const mockProbe = {
  server_name: "DeepWiki",
  server_version: "4.0.2",
  protocol_version: "2025-11-25",
  tools: [
    { name: "read_wiki_structure", description: "List a repository's wiki pages", openclaw_name: "deepwiki__read_wiki_structure", truncated: false, visible: true },
    { name: "read_wiki_contents", description: "Read a wiki page", openclaw_name: "deepwiki__read_wiki_contents", truncated: false, visible: true },
    { name: "ask_wiki_question", description: "Ask about a repository", openclaw_name: "deepwiki__ask_wiki_question", truncated: false, visible: true },
  ],
  warnings: [],
};

export const MCP_AGENT_SERVER_ID = "6a6a6a6a-5555-4555-8555-555555555555";

/** An Agent MCP Server of the mock Agent, as its editors receive it. */
export const mockAgentServer = {
  ...mockMcpServer,
  id: MCP_AGENT_SERVER_ID,
  identifier: "sentry",
  name: "Sentry",
  description: null,
  scope: "agent",
  tool_exclude: null,
  url: "https://mcp.sentry.dev/mcp",
  headers: [],
  agent_id: "33333333-3333-4333-8333-333333333333",
  agent_name: "Test Agent",
  restricted: false,
};

export function agentMcpServers({
  attached = false,
  pendingRestart = false,
  restricted = false,
  canManageRestricted = false,
  agentServers = [] as Record<string, unknown>[],
} = {}) {
  return {
    agent_servers: agentServers,
    can_manage_restricted: canManageRestricted,
    servers: [
      {
        id: MCP_ALL_AGENTS_ID,
        identifier: "linear",
        name: "Linear",
        description: null,
        scope: "all_agents",
        enabled: true,
        attached: false,
        active: true,
        auth_type: "bearer",
        credential_source: "organization",
        needs_sign_in: false,
        has_agent_credential: false,
      },
      {
        id: MCP_SERVER_ID,
        identifier: "deepwiki",
        name: "DeepWiki",
        description: "Read GitHub repository wikis",
        scope: "selected_agents",
        enabled: true,
        restricted,
        attached,
        active: attached,
        auth_type: "bearer",
        credential_source: "organization",
        needs_sign_in: false,
        has_agent_credential: false,
      },
      {
        id: MCP_OAUTH_ID,
        identifier: "notion",
        name: "Notion",
        description: null,
        scope: "all_agents",
        enabled: true,
        attached: false,
        active: true,
        auth_type: "oauth",
        credential_source: "missing",
        needs_sign_in: true,
        has_agent_credential: false,
      },
    ],
    pending_restart: pendingRestart,
  };
}

/** A user context whose only Membership is `role` in the test Organization. */
export function membershipContext(role: "OWNER" | "ADMIN" | "MEMBER") {
  const userId = "88888888-8888-4888-8888-888888888888";
  const organization = {
    id: TEST_ORG_ID,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    name: "AAI Labs",
    description: "Starter organization",
    is_default: false,
    owner_email: "owner@example.com",
    owner_name: "Owner",
    allowed_models: ["*"],
  };
  return {
    id: userId,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    full_name: `Org ${role.toLowerCase()}`,
    email: `${role.toLowerCase()}@example.com`,
    is_platform_admin: false,
    email_verified_at: "2024-01-01T00:00:00Z",
    organization_users: [
      {
        id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
        user_id: userId,
        organization_id: TEST_ORG_ID,
        role,
        organization,
      },
    ],
  };
}
