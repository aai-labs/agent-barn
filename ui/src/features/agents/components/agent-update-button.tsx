"use client";

import { ExternalLink, RotateCcw } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { toastError } from "@/shared/toast";

import { useRestartAgent } from "../hooks/use-restart-agent";
import type { Agent } from "../schemas";

const RELEASES_URL = "https://github.com/aai-labs/agent-barn/releases";
const UPDATE_HINT = "This Agent is running an older release. Restart it to pick up the latest.";
const RELEASES_HINT = "See what changed in the latest release";

export function AgentUpdateButton({ agent }: { agent: Agent }) {
  const restartAgent = useRestartAgent();

  const update = () => void restartAgent.restart(agent.id).catch(toastError);

  if (!agent.updateAvailable && !restartAgent.isPending) {
    return null;
  }

  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            className="af-btn af-btn-primary"
            data-testid="agent-update-button"
            disabled={restartAgent.isPending}
            onClick={update}
          >
            <RotateCcw /> {restartAgent.isPending ? "Updating…" : "Update"}
          </button>
        </TooltipTrigger>
        <TooltipContent>{UPDATE_HINT}</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <a
            className="af-btn af-btn-icon"
            data-testid="agent-update-releases-link"
            href={RELEASES_URL}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="View release notes"
          >
            <ExternalLink />
          </a>
        </TooltipTrigger>
        <TooltipContent>{RELEASES_HINT}</TooltipContent>
      </Tooltip>
    </>
  );
}
