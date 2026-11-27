"use client";

import { useState } from "react";
import { Pencil, PlugZap, Trash2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { PlusIcon } from "@/components/icons";
import { SettingsHint } from "@/components/settings/settings-hint";
import { toastError } from "@/shared/toast";

import { useDeleteMcpServer, useMcpServers } from "../hooks/use-mcp-servers";
import { useMcpServerSignIn, useMcpServerSignOut } from "../hooks/use-mcp-sign-in";
import type { McpServer } from "../schemas";
import { agentCountLabel, scopeLabel, toolFilterLabel } from "../utils";
import { McpServerDialog } from "./mcp-server-dialog";
import { Badge, McpEmptyState, McpServerIcon, RestrictedBadge, SignInBadge, TOOL_FILTER_HINT } from "./mcp-ui";

/**
 * Organization settings → MCP servers. Every member sees the list; Owners and Admins
 * (who hold `mcp_server.manage`) add, change and delete servers and see their URL and
 * authentication, which members never receive. An Agent's own servers are listed on that
 * Agent, never here, like an Agent's own integration credentials.
 */
export function McpServersPanel({ canManage }: { canManage: boolean }) {
  const { servers, isLoading, error, refetch } = useMcpServers();
  const remove = useDeleteMcpServer();
  const { signIn, signingIn, cancelSignIn } = useMcpServerSignIn();
  const signOut = useMcpServerSignOut();

  async function startSignIn(serverId: string) {
    try {
      await signIn({ serverId });
    } catch (failure) {
      toastError(failure);
    }
  }
  const [editing, setEditing] = useState<{ server: McpServer | null } | null>(null);
  const [deleting, setDeleting] = useState<McpServer | null>(null);

  async function confirmDelete() {
    if (!deleting) return;
    try {
      await remove.mutateAsync({ id: deleting.id });
      setDeleting(null);
    } catch (failure) {
      toastError(failure);
    }
  }

  return (
    <>
      <SettingsHint>
        <PlugZap size={15} style={{ flexShrink: 0, marginTop: 2 }} />
        <span>
          Each server has one organization credential, which stays in Agent Barn: Agents reach the server through the
          credential gateway and never see it.
        </span>
      </SettingsHint>

      {canManage && (
        <div className="mb-4 flex justify-end">
          <button type="button" className="af-btn af-btn-primary" onClick={() => setEditing({ server: null })}>
            <PlusIcon /> Add MCP server
          </button>
        </div>
      )}

      {isLoading && (
        <p className="m-0 py-8 text-center text-sm" style={{ color: "var(--ink-3)" }}>
          Loading MCP servers…
        </p>
      )}
      {error && (
        <AppErrorState
          error={error}
          title="We couldn't load MCP servers"
          description="The MCP server list is unavailable right now."
          onRetry={() => void refetch()}
          retryLabel="Retry"
        />
      )}
      {!isLoading && !error && servers.length === 0 && (
        <McpEmptyState title="No MCP servers yet">
          {canManage
            ? "Add a remote MCP server, such as Linear, Notion or Sentry, to let your Agents call its tools."
            : "An Owner or Admin can add MCP servers for this organization."}
        </McpEmptyState>
      )}

      {servers.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-2.5 p-0" aria-label="MCP servers">
          {servers.map((server) => (
            <li key={server.id} className="af-card flex flex-wrap items-center gap-3 p-4">
              <McpServerIcon />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate font-medium text-[var(--ink)]">{server.name}</span>
                  <span className="font-mono text-xs text-[var(--ink-4)]">{server.identifier}</span>
                  <Badge variant={server.scope === "all_agents" ? "accent" : "neutral"}>{scopeLabel(server)}</Badge>
                  {server.restricted && <RestrictedBadge />}
                  {!server.enabled && <Badge>Off</Badge>}
                  {server.signIn && <SignInBadge signIn={server.signIn} />}
                </div>
                <div className="mt-1 text-xs text-[var(--ink-3)]">
                  {[toolFilterLabel(server), `Used by ${agentCountLabel(server.agentCount)}`, server.description]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
                {server.url && <div className="mt-1 truncate font-mono text-xs text-[var(--ink-4)]">{server.url}</div>}
                {server.signIn?.status === "needs_tool_filter" && (
                  <p className="mb-0 mt-1 text-xs text-[var(--warn)]">{TOOL_FILTER_HINT}</p>
                )}
              </div>
              {canManage && (
                <div className="flex flex-wrap items-center gap-1.5">
                  {server.signIn &&
                    server.signIn.status !== "signed_in" &&
                    server.signIn.status !== "needs_tool_filter" && (
                      <button
                        type="button"
                        className="af-btn af-btn-sm af-btn-primary"
                        aria-label={`Sign in ${server.name} for the organization`}
                        disabled={signingIn !== null}
                        onClick={() => void startSignIn(server.id)}
                      >
                        {signingIn === server.id
                          ? "Signing in…"
                          : server.signIn.status === "needs_sign_in"
                            ? "Sign in again"
                            : "Sign in"}
                      </button>
                    )}
                  {signingIn === server.id && (
                    <button type="button" className="af-btn af-btn-sm af-btn-ghost" onClick={cancelSignIn}>
                      Cancel sign-in
                    </button>
                  )}
                  {(server.signIn?.status === "signed_in" || server.signIn?.status === "needs_tool_filter") && (
                    <button
                      type="button"
                      className="af-btn af-btn-sm af-btn-ghost"
                      aria-label={`Sign out ${server.name}`}
                      disabled={signOut.isPending}
                      onClick={() => signOut.mutate(server.id, { onError: (failure) => toastError(failure) })}
                    >
                      Sign out
                    </button>
                  )}
                  <button
                    type="button"
                    className="af-btn af-btn-sm"
                    aria-label={`Edit ${server.name}`}
                    onClick={() => setEditing({ server })}
                  >
                    <Pencil size={13} /> Edit
                  </button>
                  <button
                    type="button"
                    className="af-btn af-btn-sm af-btn-ghost af-btn-icon"
                    aria-label={`Delete ${server.name}`}
                    title="Delete"
                    onClick={() => setDeleting(server)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {editing && (
        <McpServerDialog
          key={editing.server?.id ?? "new"}
          server={editing.server}
          open
          onOpenChange={(open) => !open && setEditing(null)}
        />
      )}
      <ConfirmationDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete ${deleting?.name ?? "this server"}?`}
        description={
          deleting && deleting.agentCount > 0
            ? `${agentCountLabel(deleting.agentCount)} use it. They lose its tools immediately, and its Agent selections are deleted with it.`
            : "No Agents use it. Its settings and credential are deleted."
        }
        confirmLabel="Delete server"
        pendingLabel="Deleting…"
        variant="destructive"
        icon={<Trash2 size={18} />}
        isPending={remove.isPending}
        onConfirm={() => void confirmDelete()}
      />
    </>
  );
}
