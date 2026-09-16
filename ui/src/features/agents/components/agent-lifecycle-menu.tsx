"use client";

import { RotateCcw } from "lucide-react";

import { ChevronDownIcon, PauseIcon, PlayIcon } from "@/components/icons";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toastError } from "@/shared/toast";

import { useRestartAgent } from "../hooks/use-restart-agent";
import { useStartAgent } from "../hooks/use-start-agent";
import { useStopAgent } from "../hooks/use-stop-agent";
import type { Agent } from "../schemas";

const SEAM_LEFT = { borderTopRightRadius: 0, borderBottomRightRadius: 0, borderRightWidth: 0 };
const SEAM_RIGHT = { borderTopLeftRadius: 0, borderBottomLeftRadius: 0, paddingLeft: 10, paddingRight: 10 };

export function AgentLifecycleMenu({ agent }: { agent: Agent }) {
  const startAgent = useStartAgent();
  const stopAgent = useStopAgent();
  const restartAgent = useRestartAgent();

  const busy = startAgent.isPending || stopAgent.isPending || restartAgent.isPending;

  const start = () => void startAgent.mutateAsync(agent.id).catch(toastError);
  const pause = () => void stopAgent.mutateAsync(agent.id).catch(toastError);
  const restart = () => void restartAgent.restart(agent.id).catch(toastError);

  // A stopped Agent can only be started, so it gets a plain button rather than a
  // menu whose other entries would do nothing.
  if (agent.status !== "RUNNING") {
    return (
      <div data-testid="agent-lifecycle-menu">
        <button className="af-btn" disabled={busy} onClick={start}>
          <PlayIcon /> {startAgent.isPending ? "Starting…" : "Start"}
        </button>
      </div>
    );
  }

  return (
    <div className="flex" data-testid="agent-lifecycle-menu">
      <button className="af-btn" style={SEAM_LEFT} disabled={busy} onClick={pause}>
        <PauseIcon />{" "}
        {restartAgent.isPending ? "Restarting…" : stopAgent.isPending ? "Pausing…" : "Pause"}
      </button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            className="af-btn"
            style={SEAM_RIGHT}
            disabled={busy}
            aria-label="More lifecycle actions"
          >
            <ChevronDownIcon size={13} />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={pause}>
            <PauseIcon /> Pause
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={restart}>
            <RotateCcw /> Restart
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
