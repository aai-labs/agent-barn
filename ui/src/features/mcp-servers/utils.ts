import { createQueryKeyStructure } from "@/shared/query-keys";

import type { McpServer, McpSignIn } from "./schemas";

/** Organization-scoped: listed in the Organization switch's eviction set. */
export const mcpServersKey = createQueryKeyStructure("mcp-servers");

export const MCP_IDENTIFIER_MAX_LENGTH = 20;

/** The identifier the API derives from a name. Shown while typing; never sent. */
export function identifierFromName(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, MCP_IDENTIFIER_MAX_LENGTH)
    .replace(/-+$/g, "");
}

export function agentCountLabel(count: number): string {
  if (count === 0) return "No agents";
  return count === 1 ? "1 agent" : `${count} agents`;
}

export function scopeLabel(server: Pick<McpServer, "scope">): string {
  if (server.scope === "agent") return "This Agent only";
  return server.scope === "all_agents" ? "All Agents" : "Selected Agents";
}

export function toolFilterLabel(server: Pick<McpServer, "toolInclude" | "toolExclude">): string {
  if (server.toolInclude) {
    const count = server.toolInclude.length;
    return count === 1 ? "Only 1 tool" : `Only ${count} tools`;
  }
  if (server.toolExclude) {
    const count = server.toolExclude.length;
    return count === 1 ? "All tools but 1" : `All tools but ${count}`;
  }
  return "All tools";
}

export function signInLabel(signIn: McpSignIn): string {
  if (signIn.status === "signed_in") return "Signed in";
  if (signIn.status === "needs_sign_in") return "Needs sign-in again";
  return "Not signed in";
}
