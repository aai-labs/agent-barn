"use client";

import { useState } from "react";
import { MoreHorizontal, Plus } from "lucide-react";

import { AppErrorState } from "@/components/app-error-state";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toastError } from "@/shared/toast";

import { useAgentSizeActions, useAgentSizes } from "../hooks/use-agent-sizes";
import type { AgentSize } from "../schemas";
import { agentCountLabel, formatCpu, formatMemory } from "../utils";
import { AgentSizeDialog } from "./agent-size-dialog";

/**
 * Platform → Settings → Agent sizes: the catalog of CPU and memory Agents run with.
 *
 * Every Agent runs on the default size. The default can be neither disabled nor deleted;
 * making another size the default is how it changes. Switching the default and disabling a size
 * Agents are on both ask first, saying which Agents move and which stay.
 */
export function AgentSizesSettings() {
  const { sizes, isLoadingSizes, sizesError, reloadSizes } = useAgentSizes();
  const { update, remove } = useAgentSizeActions();
  // Each opening gets a fresh form, keyed on this count.
  const [editing, setEditing] = useState<{ size: AgentSize | null; opening: number } | null>(null);
  const [deleting, setDeleting] = useState<AgentSize | null>(null);
  const [confirming, setConfirming] = useState<{ size: AgentSize; change: "default" | "disable" } | null>(null);

  if (isLoadingSizes) return <p className="m-0">Loading Agent sizes…</p>;
  if (sizesError) {
    return <AppErrorState error={sizesError} title="Could not load Agent sizes" onRetry={() => void reloadSizes()} />;
  }

  const open = (size: AgentSize | null) => setEditing((current) => ({ size, opening: (current?.opening ?? 0) + 1 }));
  const currentDefault = sizes.find((size) => size.isDefault);
  const toggleEnabled = (size: AgentSize) => {
    if (size.enabled && size.agentCount > 0) {
      setConfirming({ size, change: "disable" });
      return;
    }
    update.mutate({ id: size.id, data: { enabled: !size.enabled } }, { onError: (error) => toastError(error) });
  };
  const confirm = () => {
    if (!confirming) return;
    const data = confirming.change === "default" ? { isDefault: true as const } : { enabled: false };
    update.mutate(
      { id: confirming.size.id, data },
      { onSuccess: () => setConfirming(null), onError: (error) => toastError(error) },
    );
  };

  return (
    <>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <p className="m-0 min-w-0 flex-1 basis-[24rem] text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          A change to a size reaches each Agent on it the next time it starts.
        </p>
        <button type="button" className="af-btn af-btn-sm" onClick={() => open(null)}>
          <Plus size={14} /> Add size
        </button>
      </div>

      <div className="af-card overflow-x-auto p-0">
        <table className="w-full min-w-[40rem] border-collapse text-[0.84rem]" aria-label="Agent sizes">
          <thead>
            <tr style={{ color: "var(--ink-4)" }} className="text-left text-[0.75rem]">
              <th className="px-4 py-2.5 font-medium">Name</th>
              <th className="px-4 py-2.5 font-medium">CPU</th>
              <th className="px-4 py-2.5 font-medium">Memory</th>
              <th className="px-4 py-2.5 font-medium">Enabled</th>
              <th className="px-4 py-2.5" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {sizes.map((size) => (
              <tr
                key={size.id}
                data-testid={`agent-size-row-${size.name}`}
                style={{ borderTop: "1px solid var(--line)" }}
              >
                <td className="px-4 py-3 font-medium" style={{ color: "var(--ink)" }}>
                  {size.name}
                  {size.isDefault && (
                    <span
                      className="ml-2 rounded-full px-2 py-0.5 text-[0.7rem] font-medium"
                      style={{ background: "var(--bg-soft)", color: "var(--ink-3)" }}
                    >
                      Default
                    </span>
                  )}
                </td>
                <RequestLimit request={formatCpu(size.cpuRequestMillicores)} limit={formatCpu(size.cpuLimitMillicores)} />
                <RequestLimit
                  request={formatMemory(size.memoryRequestBytes)}
                  limit={formatMemory(size.memoryLimitBytes)}
                />
                <td className="px-4 py-3">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={size.enabled}
                    aria-label={`${size.name} enabled`}
                    title={size.isDefault ? "The default size is always enabled" : undefined}
                    disabled={size.isDefault || update.isPending}
                    onClick={() => toggleEnabled(size)}
                    className="relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                    style={{ backgroundColor: size.enabled ? "var(--ink)" : "var(--line)" }}
                  >
                    <span
                      className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${size.enabled ? "translate-x-4" : ""}`}
                    />
                  </button>
                </td>
                <td className="px-4 py-3 text-right">
                  <DropdownMenu modal={false}>
                    <DropdownMenuTrigger asChild>
                      <button type="button" className="af-btn af-btn-ghost af-btn-icon" aria-label={`${size.name} actions`}>
                        <MoreHorizontal size={16} />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onSelect={() => open(size)}>Edit</DropdownMenuItem>
                      {!size.isDefault && (
                        <DropdownMenuItem
                          disabled={!size.enabled}
                          onSelect={() => setConfirming({ size, change: "default" })}
                        >
                          Make default
                        </DropdownMenuItem>
                      )}
                      {!size.isDefault && (
                        <DropdownMenuItem variant="destructive" onSelect={() => setDeleting(size)}>
                          Delete
                        </DropdownMenuItem>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing && (
        <AgentSizeDialog
          key={editing.opening}
          size={editing.size}
          open
          onOpenChange={(isOpen) => !isOpen && setEditing(null)}
        />
      )}

      <ConfirmationDialog
        open={confirming !== null}
        onOpenChange={(isOpen) => !isOpen && setConfirming(null)}
        title={
          confirming?.change === "default"
            ? `Make ${confirming.size.name} the default?`
            : `Disable ${confirming?.size.name ?? "this size"}?`
        }
        description={confirming ? confirmationText(confirming.size, confirming.change, currentDefault) : ""}
        confirmLabel={confirming?.change === "default" ? "Make default" : "Disable size"}
        pendingLabel="Saving…"
        isPending={update.isPending}
        onConfirm={confirm}
      />

      <ConfirmationDialog
        open={deleting !== null}
        onOpenChange={(isOpen) => !isOpen && setDeleting(null)}
        variant="destructive"
        title={`Delete ${deleting?.name ?? "this size"}?`}
        description="It is removed from the catalog. To keep it out of use but restore it later, disable it instead."
        confirmLabel="Delete size"
        pendingLabel="Deleting…"
        isPending={remove.isPending}
        onConfirm={() => {
          if (!deleting) return;
          remove.mutate(deleting.id, {
            onSuccess: () => setDeleting(null),
            onError: (error) => toastError(error),
          });
        }}
      />
    </>
  );
}

function confirmationText(size: AgentSize, change: "default" | "disable", currentDefault?: AgentSize): string {
  if (change === "disable") {
    return `${agentCountLabel(size.agentCount)} on ${size.name} stay on it, and keep starting on it, until someone changes their size. Disabling only stops it being chosen again.`;
  }
  const following = currentDefault?.followingAgentCount ?? 0;
  const moves =
    following > 0
      ? `${agentCountLabel(following)} that follow ${currentDefault?.name ?? "the default"} move to ${size.name} the next time each starts. `
      : `New agents start on ${size.name}. `;
  return `${moves}Agents given a size keep it, and organizations that can choose are allowed ${currentDefault?.name ?? "the old default"}, so none loses a size it could choose.`;
}

function RequestLimit({ request, limit }: { request: string; limit: string }) {
  return (
    <td className="px-4 py-3">
      <span style={{ color: "var(--ink)" }}>{limit}</span>
      <span className="block text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
        request {request}
      </span>
    </td>
  );
}
