"use client";

import { RotateCcw } from "lucide-react";

import { toastError } from "@/shared/toast";

import { useRestartAgent } from "../hooks/use-restart-agent";
import type { Agent } from "../schemas";

const UPDATE_HINT = "A platform update is available. Restart this Agent to apply it.";

export function AgentUpdateButton({ agent }: { agent: Agent }) {
  const restartAgent = useRestartAgent();

  const update = () => void restartAgent.restart(agent.id).catch(toastError);

  return (
    <button
      className="af-btn af-btn-primary"
      data-testid="agent-update-button"
      disabled={restartAgent.isPending}
      onClick={update}
      title={UPDATE_HINT}
    >
      <RotateCcw /> {restartAgent.isPending ? "Updating…" : "Update"}
    </button>
  );
}
