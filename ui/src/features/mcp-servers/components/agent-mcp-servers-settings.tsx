"use client";

import Link from "next/link";
import { useState } from "react";
import { CircleAlert, KeyRound, Pencil, Plus, Trash2 } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { SettingsSection } from "@/components/settings/settings-section";
import type { Agent } from "@/features/agents/schemas";
import { toastError } from "@/shared/toast";

import { useAgentMcpServers } from "../hooks/use-agent-mcp-servers";
import { useDeleteMcpServer } from "../hooks/use-mcp-servers";
import { useMcpServerSignIn } from "../hooks/use-mcp-sign-in";
import type { AgentMcpServer, McpServer } from "../schemas";
import { toolFilterLabel } from "../utils";
import { AgentMcpCredentialDialog } from "./agent-mcp-credential-dialog";
import { McpServerDialog } from "./mcp-server-dialog";
import { Badge, McpServerIcon, McpSwitch, RestrictedBadge, SignInBadge } from "./mcp-ui";

const RESTRICTED_HINT = "Restricted: only organization Owners and Admins can change it for an Agent";

/** Which account the Agent reaches the server as. */
function credentialLabel(server: AgentMcpServer): string {
  const oauth = server.authType === "oauth";
  if (server.credentialSource === "agent") {
    if (server.needsSignIn) return "This Agent's own sign-in has expired";
    return oauth ? "Signed in with this Agent's own account" : "Uses this Agent's own credential";
  }
  if (server.credentialSource === "missing") return "Needs a sign-in: nobody has signed in for the organization";
  if (server.needsSignIn) return "The organization's sign-in has expired";
  return oauth ? "Uses the organization's sign-in" : "Uses the organization's credential";
}

function stateLabel(server: AgentMcpServer): string {
  if (!server.enabled) return "Turned off for the organization";
  if (server.scope === "all_agents") return "On for every Agent";
  return server.attached ? "On for this Agent" : "Off for this Agent";
}

/**
 * Agent configuration → MCP servers: which of the Organization's servers this Agent uses,
 * and the Agent's own servers. All Agents servers are always on; Selected Agents ones are
 * switched per Agent, restricted ones by Owners and Admins only. Turning one off takes
 * effect at once; turning one on, or adding an Agent server, reaches the runtime at its
 * next start.
 */
export function AgentMcpServersSettings({
  agent,
  canEdit,
  canRestart,
}: {
  agent: Agent;
  /** `agent.update` and `agent.secret.manage`. */
  canEdit: boolean;
  /** `agent.lifecycle.manage`. */
  canRestart: boolean;
}) {
  const {
    servers,
    agentServers,
    canManageRestricted,
    pendingRestart,
    isLoading,
    error,
    refetch,
    save,
    isSaving,
    setCredential,
    removeCredential,
  } = useAgentMcpServers(agent.id);
  const { signIn, signingIn, cancelSignIn } = useMcpServerSignIn();
  const [credentialFor, setCredentialFor] = useState<AgentMcpServer | null>(null);
  const [removing, setRemoving] = useState<AgentMcpServer | null>(null);
  const [ownEditing, setOwnEditing] = useState<{
    server: McpServer | null;
  } | null>(null);
  const [ownDeleting, setOwnDeleting] = useState<McpServer | null>(null);
  const deleteOwn = useDeleteMcpServer();
  const mayChange = (server: AgentMcpServer) => !server.restricted || canManageRestricted;

  async function confirmDeleteOwn() {
    if (!ownDeleting) return;
    try {
      await deleteOwn.mutateAsync({ id: ownDeleting.id, agentId: agent.id });
      setOwnDeleting(null);
    } catch (failure) {
      toastError(failure);
    }
  }

  async function signInForAgent(serverId: string) {
    try {
      await signIn({ serverId, agentId: agent.id });
    } catch (failure) {
      toastError(failure);
    }
  }

  async function confirmRemove() {
    if (!removing) return;
    try {
      await removeCredential.mutateAsync(removing.id);
      setRemoving(null);
    } catch (failure) {
      toastError(failure);
    }
  }
  // The shared servers' switches are always live: a change is a draft until Apply saves it.
  const [draft, setDraft] = useState<Set<string> | null>(null);
  const attached = new Set(servers.filter((server) => server.attached).map((server) => server.id));
  const selection = draft ?? attached;
  const dirty =
    draft !== null && (draft.size !== attached.size || [...draft].some((serverId) => !attached.has(serverId)));
  const running = agent.status === "RUNNING";
  const restartOnApply = running && canRestart;

  function toggle(serverId: string, on: boolean) {
    const next = new Set(selection);
    if (on) next.add(serverId);
    else next.delete(serverId);
    setDraft(next);
  }

  async function apply() {
    // Only Selected Agents servers carry attachments; the API refuses any other id.
    const selectable = new Set(
      servers.filter((server) => server.scope === "selected_agents").map((server) => server.id),
    );
    await save({
      attachedServerIds: [...selection].filter((serverId) => selectable.has(serverId)),
      restart: restartOnApply,
    });
    setDraft(null);
  }

  const credentialTone = (server: AgentMcpServer) =>
    server.needsSignIn ? "var(--err)" : server.credentialSource === "agent" ? "var(--accent-ink)" : "var(--ink-3)";

  const ownServersList = (
    <section aria-label="This Agent's own MCP servers" className="flex flex-col gap-2.5">
      <GroupLabel title="This Agent" count={agentServers.length} />
      {agentServers.length === 0 && (
        <p className="m-0 text-sm text-[var(--ink-4)]">
          No servers of its own yet. Add one only this Agent should reach, with its own credential.
        </p>
      )}
      {agentServers.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-2.5 p-0" aria-label="This Agent's own MCP servers">
          {agentServers.map((server) => (
            <li key={server.id} className="af-card flex flex-wrap items-center gap-3 p-4">
              <McpServerIcon />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate font-medium text-[var(--ink)]">{server.name}</span>
                  <span className="font-mono text-xs text-[var(--ink-4)]">{server.identifier}</span>
                  {server.enabled ? <Badge variant="ok">On</Badge> : <Badge>Off</Badge>}
                  {server.signIn && <SignInBadge signIn={server.signIn} />}
                </div>
                <div className="mt-1 text-xs text-[var(--ink-3)]">{toolFilterLabel(server)}</div>
                {server.url && <div className="mt-1 truncate font-mono text-xs text-[var(--ink-4)]">{server.url}</div>}
              </div>
              {canEdit && (
                <div className="flex flex-wrap items-center gap-1.5">
                  {server.signIn && server.signIn.status !== "signed_in" && (
                    <button
                      type="button"
                      className="af-btn af-btn-sm af-btn-primary"
                      aria-label={`Sign in ${server.name} for this Agent`}
                      disabled={signingIn !== null}
                      onClick={() => void signInForAgent(server.id)}
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
                  <button
                    type="button"
                    className="af-btn af-btn-sm"
                    aria-label={`Edit ${server.name}`}
                    onClick={() => setOwnEditing({ server })}
                  >
                    <Pencil size={13} /> Edit
                  </button>
                  <button
                    type="button"
                    className="af-btn af-btn-sm af-btn-ghost af-btn-icon"
                    aria-label={`Delete ${server.name}`}
                    title="Delete"
                    onClick={() => setOwnDeleting(server)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );

  const organizationServersList = (
    <>
      {running && dirty && !canRestart && (
        <p className="m-0 text-[0.8rem] text-[var(--ink-3)]">Servers you turn on reach the Agent at its next start.</p>
      )}
      {isLoading && <p className="m-0 text-sm text-[var(--ink-3)]">Loading MCP servers…</p>}
      {error && (
        <AppErrorState
          error={error}
          title="We couldn't load MCP servers"
          description="This Agent's MCP servers are unavailable right now."
          onRetry={() => void refetch()}
          retryLabel="Retry"
        />
      )}
      {!isLoading && !error && servers.length === 0 && (
        <p className="m-0 text-sm text-[var(--ink-4)]">
          The organization has no shared MCP servers.{" "}
          <Link
            href={`/dashboard/${agent.organizationId}/settings?tab=mcp-servers`}
            className="font-medium underline-offset-2 hover:underline"
            style={{ color: "var(--accent-ink)" }}
          >
            Organization settings
          </Link>{" "}
          is where Owners and Admins add them.
        </p>
      )}
      {servers.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-2.5 p-0" aria-label="Agent MCP servers">
          {servers.map((server) => {
            const selectable = server.scope === "selected_agents" && server.enabled && mayChange(server);
            const on = server.scope === "all_agents" ? server.enabled : server.enabled && selection.has(server.id);
            return (
              <li key={server.id} className="af-card flex items-start gap-3 p-4">
                <McpServerIcon />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-medium text-[var(--ink)]">{server.name}</span>
                    <span className="font-mono text-xs text-[var(--ink-4)]">{server.identifier}</span>
                    <Badge variant={server.scope === "all_agents" ? "accent" : "neutral"}>
                      {server.scope === "all_agents" ? "All Agents" : "Selected Agents"}
                    </Badge>
                    {server.restricted && <RestrictedBadge />}
                  </div>
                  <div className="mt-1 text-xs text-[var(--ink-3)]">
                    {selectable ? (on ? "On for this Agent" : "Off for this Agent") : stateLabel(server)}
                    {server.description ? ` · ${server.description}` : ""}
                  </div>
                  <div
                    className="mt-1 flex items-center gap-1.5 text-xs"
                    style={{ color: credentialTone(server) }}
                    data-testid={`mcp-credential-${server.identifier}`}
                  >
                    <KeyRound size={12} aria-hidden="true" />
                    {credentialLabel(server)}
                  </div>
                  {canEdit && !mayChange(server) && (
                    <p className="mb-0 mt-2 text-xs text-[var(--ink-4)]">
                      Only organization Owners and Admins can change it for this Agent.
                    </p>
                  )}
                  {canEdit && mayChange(server) && (
                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      {server.authType === "oauth" && (!server.hasAgentCredential || server.needsSignIn) && (
                        <button
                          type="button"
                          className="af-btn af-btn-sm"
                          disabled={signingIn !== null}
                          onClick={() => void signInForAgent(server.id)}
                        >
                          {signingIn === server.id
                            ? "Signing in…"
                            : server.hasAgentCredential
                              ? "Sign in again"
                              : "Sign in with this Agent's own account"}
                        </button>
                      )}
                      {signingIn === server.id && (
                        <button type="button" className="af-btn af-btn-sm af-btn-ghost" onClick={cancelSignIn}>
                          Cancel sign-in
                        </button>
                      )}
                      {server.authType !== "oauth" && (
                        <button type="button" className="af-btn af-btn-sm" onClick={() => setCredentialFor(server)}>
                          {server.hasAgentCredential
                            ? "Change this Agent's credential"
                            : "Use this Agent's own credential"}
                        </button>
                      )}
                      {server.hasAgentCredential && (
                        <button
                          type="button"
                          className="af-btn af-btn-sm af-btn-ghost"
                          onClick={() => setRemoving(server)}
                        >
                          Use the organization&apos;s instead
                        </button>
                      )}
                    </div>
                  )}
                </div>
                <McpSwitch
                  checked={on}
                  label={`${server.name} for this Agent`}
                  disabled={!canEdit || !selectable || isSaving}
                  title={
                    server.scope === "all_agents"
                      ? "On for every Agent in the organization"
                      : !server.enabled
                        ? "Turned off in organization settings"
                        : !mayChange(server)
                          ? RESTRICTED_HINT
                          : undefined
                  }
                  onChange={(next) => toggle(server.id, next)}
                />
              </li>
            );
          })}
        </ul>
      )}
      {servers.length > 0 && canEdit && (
        <p className="m-0 text-xs text-[var(--ink-4)]">
          An Agent can use its own account or credential for a server instead of the organization&apos;s. That changes
          which account it acts as, not whether it has the server.
        </p>
      )}
    </>
  );

  return (
    <div className="flex flex-col gap-7">
      {pendingRestart && (
        <Alert>
          <CircleAlert />
          <AlertTitle>Restart to apply</AlertTitle>
          <AlertDescription>
            This Agent is running with a different set of MCP servers. Servers turned off are already cut off; servers
            turned on appear after the Agent restarts.
          </AlertDescription>
        </Alert>
      )}
      {ownServersList}
      {/* Unstyled: no outer card. There is no Edit step: the switches are live, and Apply (or
          Apply & Restart) appears on the group's label row once something changed. */}
      <SettingsSection
        unstyled
        title="MCP servers"
        description="The organization's shared MCP servers this Agent can call tools on."
        canEdit={canEdit}
        editing={dirty}
        onApply={apply}
        applyLabel={restartOnApply ? "Apply & Restart" : "Apply"}
        applyPendingLabel={restartOnApply ? "Applying & Restarting…" : "Applying…"}
        confirm={
          restartOnApply
            ? {
                title: "Apply MCP servers and restart the Agent?",
                description:
                  "This saves which servers the Agent uses, stops it, and starts it again so its runtime lists them.",
              }
            : running
              ? {
                  title: "Apply MCP servers?",
                  description:
                    "Servers you turn off are cut off at once. Servers you turn on reach the Agent at its next start.",
                }
              : {
                  title: "Apply MCP servers?",
                  description: "This saves which servers the Agent uses. They apply when it next starts.",
                }
        }
        actionsRenderer={(actions) => (
          <div className="flex flex-col gap-2.5">
            <GroupLabel
              title="Organization shared"
              count={servers.length}
              actions={
                dirty ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      className="af-btn af-btn-ghost"
                      disabled={isSaving}
                      onClick={() => setDraft(null)}
                    >
                      Discard
                    </button>
                    {actions}
                  </div>
                ) : undefined
              }
            />
            {organizationServersList}
          </div>
        )}
      >
        {null}
      </SettingsSection>
      {ownEditing && (
        <McpServerDialog
          key={ownEditing.server?.id ?? "new-agent-server"}
          server={ownEditing.server}
          agentId={agent.id}
          open
          onOpenChange={(open) => !open && setOwnEditing(null)}
        />
      )}
      <ConfirmationDialog
        open={ownDeleting !== null}
        onOpenChange={(open) => !open && setOwnDeleting(null)}
        title={`Delete ${ownDeleting?.name ?? "this server"}?`}
        description="This Agent loses its tools immediately. Its settings and credential are deleted."
        confirmLabel="Delete server"
        pendingLabel="Deleting…"
        variant="destructive"
        icon={<Trash2 size={18} />}
        isPending={deleteOwn.isPending}
        onConfirm={() => void confirmDeleteOwn()}
      />
      {credentialFor && (
        <AgentMcpCredentialDialog
          key={credentialFor.id}
          server={credentialFor}
          open
          onOpenChange={(open) => {
            if (!open) {
              setCredentialFor(null);
              setCredential.reset();
            }
          }}
          onSave={(data) => setCredential.mutateAsync({ serverId: credentialFor.id, data })}
          isSaving={setCredential.isPending}
          error={setCredential.error}
        />
      )}
      <ConfirmationDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Use the organization's credential for ${removing?.name ?? "this server"}?`}
        description={
          removing?.authType === "oauth"
            ? "This Agent's own sign-in is forgotten. It uses the organization's sign-in from its next request, or none if nobody has signed in for the organization."
            : "This Agent's own credential is deleted. It uses the organization's credential from its next request."
        }
        confirmLabel="Use the organization's"
        pendingLabel="Switching…"
        isPending={removeCredential.isPending}
        onConfirm={() => void confirmRemove()}
      />
    </div>
  );
}

/** A plain label over one group of servers, with the group's actions on its right. */
function GroupLabel({ title, count, actions }: { title: string; count: number; actions?: React.ReactNode }) {
  return (
    <div className="flex min-h-9 flex-wrap items-center justify-between gap-2">
      <h3 className="m-0 flex items-center gap-2 text-[0.95rem] font-semibold text-[var(--ink)]">
        {title}
        {count > 0 && <span className="text-[0.8rem] font-normal text-[var(--ink-4)]">{count}</span>}
      </h3>
      {actions}
    </div>
  );
}

/**
 * "Add server for this Agent", for the MCP section's heading. It opens its own dialog; the
 * section's list picks the new server up through the shared query.
 */
export function AddAgentMcpServerButton({ agentId, canEdit }: { agentId: string; canEdit: boolean }) {
  const [open, setOpen] = useState(false);
  if (!canEdit) return null;
  return (
    <>
      <button type="button" className="af-btn af-btn-primary" onClick={() => setOpen(true)}>
        <Plus size={14} /> Add server for this Agent
      </button>
      {open && <McpServerDialog server={null} agentId={agentId} open onOpenChange={setOpen} />}
    </>
  );
}
