"use client";

import { RefreshCw, RotateCcw } from "lucide-react";

import { toastError } from "@/shared/toast";

import { useRestartAgent } from "../hooks/use-restart-agent";
import type { Agent } from "../schemas";
import { currentModelOf, formatModelName } from "../utils";

/**
 * Says what a restart would switch this Agent onto.
 *
 * Only rendered when a running pod started on a different model than the one that
 * resolves now — normally because the Organization changed its default underneath an
 * inheriting Agent. The runtime reads its model once at container start, so until
 * someone restarts it the Agent really is still serving the old one; naming the new
 * value here keeps the primary display honest about the present.
 */
export function PendingModelNote({ pendingModel }: { pendingModel: string }) {
  if (!pendingModel) return null;
  return (
    <div className="mt-0.5 text-[0.72rem]" style={{ color: "var(--ink-4)" }}>
      Pending switch to <span className="font-mono">{formatModelName(pendingModel)}</span> on restart
    </div>
  );
}

/** The Agent detail page's version of {@link PendingModelNote}, with a restart action for lifecycle managers. */
export function PendingModelBanner({ agent, canRestart }: { agent: Agent; canRestart: boolean }) {
  const restartAgent = useRestartAgent();
  if (!agent.pendingModel) return null;

  const restart = () => void restartAgent.restart(agent.id).catch(toastError);
  const busy = restartAgent.isPending || agent.updateInProgress;

  return (
    <div
      data-testid="agent-pending-model-banner"
      className="mb-6 flex items-center justify-between gap-3 rounded-2xl px-4 py-3.5"
      style={{
        background: "var(--warn-soft)",
        border: "1px solid color-mix(in srgb, var(--warn) 25%, transparent)",
      }}
    >
      <div className="flex items-center gap-3">
        <span
          className="grid h-8 w-8 flex-shrink-0 place-items-center rounded-lg"
          style={{ background: "color-mix(in srgb, var(--warn) 14%, transparent)", color: "var(--warn)" }}
        >
          <RefreshCw size={16} />
        </span>
        <p className="m-0 text-[0.844rem] leading-relaxed" style={{ color: "var(--warn)" }}>
          {agent.name} is still running on{" "}
          <span className="font-mono">{formatModelName(currentModelOf(agent))}</span>. Restart it to switch
          to <span className="font-mono">{formatModelName(agent.pendingModel)}</span>.
        </p>
      </div>
      {canRestart && (
        <button
          className="af-btn af-btn-sm flex-shrink-0"
          data-testid="agent-pending-model-restart"
          disabled={busy}
          onClick={restart}
        >
          <RotateCcw size={14} /> {restartAgent.isPending ? "Restarting…" : "Restart"}
        </button>
      )}
    </div>
  );
}
