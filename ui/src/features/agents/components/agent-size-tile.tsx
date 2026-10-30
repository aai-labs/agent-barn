"use client";

import { Lock, RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { AgentSizeSelect } from "@/features/agent-sizes/components/agent-size-select";
import { useOrganizationAgentSizes } from "@/features/agent-sizes/hooks/use-organization-agent-sizes";
import { describeSize } from "@/features/agent-sizes/utils";
import { toastError } from "@/shared/toast";

import { useRestartAgent } from "../hooks/use-restart-agent";
import { useSetAgentSize } from "../hooks/use-set-agent-size";
import type { Agent } from "../schemas";
import { canAgent } from "../utils";

/**
 * The Agent's CPU and memory in the Profile's "Runtime & deployment" block.
 *
 * Owners and Admins of an Organization the platform lets choose change it here. The change is
 * saved at once and never restarts the Agent: a running one keeps its resources until its next
 * start, and says so meanwhile, with a restart for whoever may restart it. A size a Platform
 * Administrator set is shown locked instead.
 */
export function AgentSizeTile({ agent }: { agent: Agent }) {
  const { agentSizes } = useOrganizationAgentSizes();
  const setSize = useSetAgentSize();
  const restartAgent = useRestartAgent();
  const canRestart = canAgent(agent, "agent.lifecycle.manage");
  const choices =
    !agent.agentSizeSetByPlatform && canAgent(agent, "agent.size.manage") && agentSizes?.canChoose
      ? agentSizes.sizes
      : null;
  const size = agent.agentSize;
  const defaultId = choices?.find((choice) => choice.isDefault)?.id ?? "";
  // A size withdrawn or disabled since it was chosen still applies to this Agent.
  const unavailable = size && choices && !choices.some((choice) => choice.id === size.id) ? size : null;

  return (
    <div
      className="rounded-xl px-3.5 py-3"
      data-testid="agent-size-tile"
      style={{ border: "1px solid var(--line)", background: "var(--bg-soft)" }}
    >
      <div className="text-[0.72rem] font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink-4)" }}>
        Agent spec
      </div>
      {choices ? (
        <div className="mt-1.5">
          <AgentSizeSelect
            sizes={choices}
            value={agent.agentSizeId ?? defaultId}
            unavailable={unavailable}
            disabled={setSize.isPending}
            onChange={(choice) =>
              setSize.mutate(
                { agentId: agent.id, agentSizeId: choice.isDefault ? null : choice.id },
                {
                  onSuccess: (updated) =>
                    toast.success(
                      updated.pendingSize
                        ? `${updated.name} moves to ${choice.name} when it restarts`
                        : `${updated.name} will start on ${choice.name}`,
                    ),
                  onError: (error) => toastError(error),
                },
              )
            }
          />
        </div>
      ) : (
        <div className="mt-1 text-[0.9rem]" style={{ color: "var(--ink-2)" }}>
          {size ? describeSize(size) : "—"}
          {size && agent.agentSizeId === null && (
            <span className="ml-1.5 text-[0.8rem]" style={{ color: "var(--ink-4)" }}>
              (default)
            </span>
          )}
        </div>
      )}
      {agent.agentSizeSetByPlatform && (
        <div
          className="mt-1 flex items-center gap-1 text-[0.72rem]"
          data-testid="agent-size-set-by-platform"
          style={{ color: "var(--ink-4)" }}
        >
          <Lock size={11} /> Set by platform
        </div>
      )}
      {agent.pendingSize && (
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <span className="text-[0.72rem]" data-testid="agent-pending-size-note" style={{ color: "var(--ink-4)" }}>
            Pending: applies on restart
          </span>
          {canRestart && (
            <button
              type="button"
              className="af-btn af-btn-sm"
              data-testid="agent-pending-size-restart"
              disabled={restartAgent.isPending || agent.updateInProgress}
              onClick={() => void restartAgent.restart(agent.id).catch(toastError)}
            >
              <RotateCcw size={13} /> {restartAgent.isPending ? "Restarting…" : "Restart"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
