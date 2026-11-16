"use client";

import { useState } from "react";

import { AgentConfigurationSection } from "@/features/agents/components/agent-configuration-section";
import type { Agent } from "@/features/agents/schemas";

import { useAgentSsh, useSshCredentials } from "../hooks/use-ssh";

export function AgentSshPanel({ agent }: { agent: Agent }) {
  const query = useAgentSsh(agent.id);
  const [search, setSearch] = useState("");
  const available = useSshCredentials(1, search);
  const [draft, setDraft] = useState<string[] | null>(null);
  const running = agent.status === "RUNNING";
  const canRestart = agent.allowedActions.includes("agent.lifecycle.manage");
  const canManage = Boolean(query.data?.allowedActions.includes("manage"));
  const choices = Array.from(
    new Map(
      [
        ...(available.credentials ?? []),
        ...(query.data?.credentials ?? []),
      ].map((key) => [key.id, key]),
    ).values(),
  );
  return (
    <AgentConfigurationSection
      title="SSH access"
      description="Use normal SSH and Git commands. Private keys stay in Agent Barn; terminal requests appear in activity history."
      editing={draft !== null}
      canEdit={canManage && !query.error && !query.isLoading}
      onEdit={() => {
        query.mutation.reset();
        setDraft(query.data?.credentials.map((key) => key.id) ?? []);
      }}
      onCancel={() => setDraft(null)}
      onApply={async () => {
        if (draft && query.data)
          await query.mutation.mutateAsync({
            credentialIds: draft,
            expectedRevision: query.data.revision,
            restart: running,
          });
      }}
      onApplied={() => setDraft(null)}
      restartOnApply={running}
      errorsShownInline
      applyDisabled={
        !query.data ||
        query.mutation.isPending ||
        Boolean(available.error) ||
        (running && !canRestart) ||
        agent.updateInProgress ||
        (!query.data.enabled && Boolean(draft?.length))
      }
    >
      <div className="mb-4">
        <h3 className="font-semibold">SSH access</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Shared keys for ordinary SSH, Git and file transfer. Private keys stay
          in Agent Barn.
        </p>
      </div>
      {query.isLoading && <p role="status">Loading SSH access…</p>}
      {query.error && (
        <div role="alert">
          Could not load SSH access.{" "}
          <button
            className="af-btn af-btn-sm"
            onClick={() => void query.refetch()}
          >
            Retry
          </button>
        </div>
      )}
      {query.data && (
        <div className="space-y-3">
          {!query.data.enabled && (
            <p className="text-sm text-muted-foreground">
              SSH signing is disabled for this installation. An operator must
              enable it before credentials can be applied.
            </p>
          )}
          {query.data.pendingApply && (
            <p className="text-xs text-muted-foreground">
              SSH settings are waiting for the next start or Apply & Restart.
            </p>
          )}
          {draft !== null ? (
            <>
              <input
                className="af-input w-full"
                aria-label="Search SSH keys to attach"
                placeholder="Search shared SSH keys…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              {available.error && (
                <div role="alert">
                  Could not load available SSH keys.{" "}
                  <button
                    className="af-btn af-btn-sm"
                    onClick={() => void available.refetch()}
                  >
                    Retry
                  </button>
                </div>
              )}
              {choices.map((key) => (
                <label
                  key={key.id}
                  className="flex items-start gap-3 rounded-xl border p-3 text-sm"
                >
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={draft.includes(key.id)}
                    disabled={query.mutation.isPending}
                    onChange={(e) =>
                      setDraft(
                        e.target.checked
                          ? [...draft, key.id]
                          : draft.filter((id) => id !== key.id),
                      )
                    }
                  />
                  <span>
                    <span className="font-medium">{key.name}</span>
                    <span className="block text-xs text-muted-foreground">
                      {!key.enabled
                        ? "Disabled"
                        : key.mode === "unrestricted"
                          ? "Unrestricted access"
                          : `${key.servers.length} configured servers`}
                    </span>
                  </span>
                </label>
              ))}
              {!choices.length && (
                <p className="text-sm text-muted-foreground">
                  Ask an administrator to add an SSH credential in Organization
                  settings.
                </p>
              )}
            </>
          ) : (
            <>
              {!query.data.credentials.length && (
                <p className="text-sm text-muted-foreground">
                  No SSH credentials assigned.
                </p>
              )}
              {query.data.credentials.map((key) => (
                <div key={key.id} className="rounded-xl border p-3 text-sm">
                  <p className="font-medium">
                    {key.name}{" "}
                    <span className="font-normal text-muted-foreground">
                      ·{" "}
                      {!key.enabled
                        ? "Disabled"
                        : key.mode === "unrestricted"
                          ? "Unrestricted"
                          : "Specific servers"}
                    </span>
                  </p>
                  {key.servers.map((server) => (
                    <p
                      key={server.name}
                      className="mt-1 font-mono text-xs text-muted-foreground"
                    >
                      ssh ab-{key.id.replaceAll("-", "")}-{server.name}
                    </p>
                  ))}
                </div>
              ))}
            </>
          )}
          {query.mutation.error && (
            <p role="alert" className="text-sm text-destructive">
              {query.mutation.error.message}
            </p>
          )}
        </div>
      )}
    </AgentConfigurationSection>
  );
}
