"use client";

import { useState } from "react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { Button } from "@/components/ui/button";
import { getErrorDisplay } from "@/shared/api/error/get-error-display";
import type { Agent } from "@/features/agents/schemas";

import { ConnectionForm } from "./connection-form";

import { useCustomApi } from "../hooks/use-custom-api";
import type { CustomApiConnection, CustomApiWrite } from "../schemas";

export function CustomApiSettings({
  agent,
  canEdit,
}: {
  agent: Agent;
  canEdit: boolean;
}) {
  const {
    connections: data,
    isLoadingConnections: isLoading,
    connectionsError: error,
    refetchConnections: refetch,
    connectionMutation: mutation,
  } = useCustomApi(agent.id, agent.status === "RUNNING");
  const [editing, setEditing] = useState<CustomApiConnection | "new" | null>(
    null,
  );
  const [removing, setRemoving] = useState<CustomApiConnection | null>(null);
  const [draft, setDraft] = useState<CustomApiWrite | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const running = agent.status === "RUNNING";
  const canRestart = agent.allowedActions.includes("agent.lifecycle.manage");
  async function save(data: CustomApiWrite, restart?: boolean) {
    setSaveError(null);
    try {
      await mutation.mutateAsync({
        id: editing && editing !== "new" ? editing.id : undefined,
        data,
        restart,
      });
      setEditing(null);
      setDraft(null);
    } catch (error) {
      setSaveError(
        error instanceof Error ? error.message : "Could not save connection.",
      );
      setDraft(null);
    }
  }
  return (
    <section
      className="space-y-4 rounded-2xl border p-5"
      aria-labelledby="custom-api-title"
    >
      <div>
        <h2 id="custom-api-title" className="font-semibold">
          Custom API connections
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Connect APIs using stable names. Supply API-specific instructions
          through your template or Skills. Secret values are write-only.
        </p>
      </div>
      {isLoading && <p role="status">Loading connections…</p>}
      {error && (
        <div role="alert">
          <p>
            {
              getErrorDisplay(error, {
                title: "Could not load Custom API connections.",
                description: "Please retry.",
              }).title
            }
          </p>
          <Button variant="outline" onClick={() => void refetch()}>
            Retry
          </Button>
        </div>
      )}
      {saveError && (
        <p role="alert" className="text-sm text-destructive">
          {saveError}
        </p>
      )}
      {data?.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No Custom API connections configured.
        </p>
      )}
      {data?.map((connection) => (
        <div
          key={connection.id}
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3"
        >
          <div className="min-w-0">
            <h3 className="font-medium">{connection.name}</h3>
            <p className="break-all text-sm text-muted-foreground">
              {connection.slug} · {connection.baseUrl}
            </p>
            <p className="text-sm text-muted-foreground">
              {connection.isolated ? "Isolated" : "Direct credentials"}
              {connection.pendingApply ? " · Pending apply" : " · Applied"}
            </p>
          </div>
          {canEdit && (
            <div className="flex gap-2">
              <Button
                variant="outline"
                disabled={
                  mutation.isPending ||
                  agent.updateInProgress ||
                  (running && !canRestart)
                }
                onClick={() => {
                  setEditing(connection);
                  setSaveError(null);
                }}
              >
                Edit
              </Button>
              <Button
                variant="ghost"
                disabled={
                  mutation.isPending ||
                  agent.updateInProgress ||
                  (running && !canRestart)
                }
                onClick={() => setRemoving(connection)}
              >
                Delete
              </Button>
            </div>
          )}
        </div>
      ))}
      {canEdit && !editing && (
        <>
          <Button
            variant="outline"
            disabled={
              agent.updateInProgress ||
              mutation.isPending ||
              (running && !canRestart)
            }
            onClick={() => {
              setEditing("new");
              setSaveError(null);
            }}
          >
            Add Custom API
          </Button>
          {running && (
            <p className="text-sm text-muted-foreground">
              Connection changes require Apply &amp; Restart while this Agent is
              running.
            </p>
          )}
        </>
      )}
      {editing && canEdit && (
        <ConnectionForm
          key={editing === "new" ? "new" : editing.id}
          connection={editing === "new" ? undefined : editing}
          pending={
            mutation.isPending ||
            agent.updateInProgress ||
            (running && !canRestart)
          }
          onCancel={() => setEditing(null)}
          onSave={(data) => {
            if (running) setDraft(data);
            else void save(data);
          }}
        />
      )}
      <ConfirmationDialog
        open={Boolean(draft)}
        onOpenChange={(open) => {
          if (!open) setDraft(null);
        }}
        title="Apply Custom API changes and restart?"
        description="Agent Barn will check the new configuration before stopping this Agent. The connection changes take effect on restart."
        confirmLabel="Apply & Restart"
        isPending={mutation.isPending}
        confirmDisabled={
          !canEdit || agent.updateInProgress || (running && !canRestart)
        }
        onConfirm={() => (draft ? save(draft, true) : undefined)}
      />
      <ConfirmationDialog
        open={Boolean(removing)}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title="Delete Custom API connection?"
        description={`Remove ${removing?.name ?? "this connection"} and its credentials. ${running ? "Agent Barn will check the new configuration and restart this Agent to apply the removal." : "Start the Agent to apply the removal."}`}
        confirmLabel={running ? "Delete & Restart" : "Delete connection"}
        variant="destructive"
        isPending={mutation.isPending}
        confirmDisabled={
          !canEdit || agent.updateInProgress || (running && !canRestart)
        }
        onConfirm={async () => {
          try {
            await mutation.mutateAsync({
              id: removing?.id,
              remove: true,
              restart: running,
            });
            setRemoving(null);
          } catch (error) {
            setSaveError(
              error instanceof Error
                ? error.message
                : "Could not delete connection.",
            );
            setRemoving(null);
          }
        }}
      />
    </section>
  );
}
