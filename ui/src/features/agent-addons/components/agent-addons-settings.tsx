"use client";

import { useState } from "react";
import { PackagePlus, RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { AppErrorState } from "@/components/app-error-state";
import { Badge } from "@/components/badge";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { useRestartAgent } from "@/features/agents/hooks/use-restart-agent";
import type { Agent } from "@/features/agents/schemas";
import { canAgent } from "@/features/agents/utils";
import { toastError } from "@/shared/toast";

import { useAgentAddons, useWithdrawAgentAddon } from "../hooks/use-agent-addons";
import type { AgentAddon } from "../schemas";
import {
  ADDON_KIND_LABELS,
  ADDON_STATE_LABELS,
  ADDON_STATE_VARIANTS,
  addonPin,
  formatAddonDate,
} from "../utils";
import { RequestAddonDialog } from "./request-addon-dialog";

/**
 * Agent configuration → Add-ons: the libraries and tools requested for this one Agent.
 *
 * Organization Owners and Admins request them, and withdraw a request still pending; a
 * Platform Administrator approves, rejects or revokes. An approval or revocation applies the
 * next time the Agent starts, and "Pending: applies on restart" says so until then.
 */
export function AgentAddonsSettings({ agent }: { agent: Agent }) {
  const { addons, availableKinds, maxActive, isLoadingAddons, error, refetch } = useAgentAddons(agent.id);
  const withdraw = useWithdrawAgentAddon(agent.id);
  const restartAgent = useRestartAgent();
  // Each opening gets a fresh dialog, keyed on this count.
  const [requesting, setRequesting] = useState(0);
  const [withdrawing, setWithdrawing] = useState<AgentAddon | null>(null);
  const active = addons.filter((addon) => addon.state === "PENDING" || addon.state === "APPROVED").length;
  const full = maxActive > 0 && active >= maxActive;

  return (
    <div className="flex flex-col gap-4" data-testid="agent-addons-settings">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="m-0 max-w-[40rem] text-[0.84rem]" style={{ color: "var(--ink-3)" }}>
          Extra Python or npm packages, repositories, downloads or install commands for this agent. A platform
          administrator reviews each request; approved add-ons are installed when the agent starts, and the agent
          can use but not change them.
        </p>
        <button
          type="button"
          className="af-btn af-btn-primary"
          disabled={isLoadingAddons || full || availableKinds.length === 0}
          title={full ? `An agent can have at most ${maxActive} pending and approved add-ons.` : undefined}
          onClick={() => setRequesting((count) => count + 1)}
        >
          <PackagePlus size={14} /> Request add-on
        </button>
      </div>

      {agent.pendingAddons && (
        <div
          className="flex flex-wrap items-center gap-2 rounded-xl px-3.5 py-2.5 text-[0.8rem]"
          data-testid="agent-pending-addons-note"
          style={{ border: "1px solid var(--line)", background: "var(--bg-soft)", color: "var(--ink-3)" }}
        >
          Pending: applies on restart. The running agent has a different set of add-ons than the approved one.
          {canAgent(agent, "agent.lifecycle.manage") && (
            <button
              type="button"
              className="af-btn af-btn-sm"
              disabled={restartAgent.isPending || agent.updateInProgress}
              onClick={() => void restartAgent.restart(agent.id).catch(toastError)}
            >
              <RotateCcw size={13} /> {restartAgent.isPending ? "Restarting…" : "Restart"}
            </button>
          )}
        </div>
      )}

      {isLoadingAddons ? (
        <div className="h-24 animate-pulse rounded-2xl" style={{ background: "var(--bg-soft)" }} />
      ) : error ? (
        <AppErrorState
          error={error}
          title="We couldn't load this agent's add-ons"
          onRetry={() => void refetch()}
          retryLabel="Retry"
          className="min-h-[160px] p-0"
        />
      ) : addons.length === 0 ? (
        <div
          className="flex flex-col items-center justify-center rounded-2xl py-12 text-center"
          style={{ border: "1px dashed var(--line-strong)" }}
        >
          <div className="mb-1 text-[15px] font-medium" style={{ color: "var(--ink)" }}>
            No add-ons yet
          </div>
          <div className="text-[13.5px]" style={{ color: "var(--ink-3)" }}>
            Request one when the agent needs a library or tool it does not have.
          </div>
        </div>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {addons.map((addon) => (
            <AddonRow key={addon.id} addon={addon} onWithdraw={() => setWithdrawing(addon)} />
          ))}
        </ul>
      )}

      {requesting > 0 && (
        <RequestAddonDialog
          key={requesting}
          agentId={agent.id}
          agentName={agent.name}
          availableKinds={availableKinds}
          open
          onOpenChange={(open) => !open && setRequesting(0)}
        />
      )}

      {withdrawing && (
        <ConfirmationDialog
          open
          onOpenChange={(open) => !open && setWithdrawing(null)}
          title={`Withdraw ${withdrawing.name}?`}
          description="The request is no longer reviewed. To ask again, make a new request."
          confirmLabel="Withdraw"
          pendingLabel="Withdrawing…"
          variant="destructive"
          isPending={withdraw.isPending}
          onConfirm={async () => {
            try {
              await withdraw.mutateAsync(withdrawing.id);
              toast.success(`Withdrew ${withdrawing.name}`);
              setWithdrawing(null);
            } catch (failure) {
              toastError(failure);
            }
          }}
        />
      )}
    </div>
  );
}

function AddonRow({ addon, onWithdraw }: { addon: AgentAddon; onWithdraw: () => void }) {
  return (
    <li
      className="af-card flex flex-col gap-2 px-4 py-3.5"
      data-testid={`agent-addon-${addon.id}`}
      aria-label={addon.name}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[0.95rem] font-semibold" style={{ color: "var(--ink)" }}>
          {addon.name}
        </span>
        <span className="text-[0.75rem]" style={{ color: "var(--ink-4)" }}>
          {ADDON_KIND_LABELS[addon.kind]}
        </span>
        <Badge variant={ADDON_STATE_VARIANTS[addon.state]}>{ADDON_STATE_LABELS[addon.state]}</Badge>
        {addon.state === "PENDING" && (
          <button type="button" className="af-btn af-btn-sm ml-auto" onClick={onWithdraw}>
            Withdraw
          </button>
        )}
      </div>
      <code
        className="block overflow-x-auto whitespace-pre-wrap break-all rounded-lg px-2.5 py-1.5 text-[0.78rem]"
        style={{ background: "var(--bg-soft)", color: "var(--ink-2)" }}
      >
        {addonPin(addon.kind, addon.name, addon.spec)}
      </code>
      <p className="m-0 text-[0.84rem]" style={{ color: "var(--ink-2)" }}>
        <span style={{ color: "var(--ink-4)" }}>Why: </span>
        {addon.reason}
      </p>
      {addon.state === "REJECTED" && addon.rejectionReason && (
        <p className="m-0 text-[0.84rem]" data-testid="agent-addon-rejection" style={{ color: "var(--err)" }}>
          Not approved: {addon.rejectionReason}
        </p>
      )}
      <p className="m-0 text-[0.72rem]" style={{ color: "var(--ink-4)" }}>
        Requested {formatAddonDate(addon.createdAt)}
        {addon.requestedBy ? ` by ${addon.requestedBy.fullName ?? addon.requestedBy.email}` : ""}
        {addon.decidedAt ? ` · ${ADDON_STATE_LABELS[addon.state].toLowerCase()} ${formatAddonDate(addon.decidedAt)}` : ""}
      </p>
    </li>
  );
}
