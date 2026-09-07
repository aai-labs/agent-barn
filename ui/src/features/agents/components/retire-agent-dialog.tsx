"use client";

import { useState } from "react";
import { Check } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { toastError } from "@/shared/toast";

import { useAgentMemory } from "../hooks/use-agent-memory";
import { useAgents } from "../hooks/use-agents";
import type { Agent } from "../schemas";
import { AgentAvatar } from "./agent-avatar";

/** Retiring an agent erases what it learned along with everything else it owns.
 *
 *  The carry-over here is the reason that is acceptable: it is offered at the one
 *  moment someone knows the memory is about to go. Expecting them to have shared
 *  the useful facts beforehand would be expecting foresight they do not have —
 *  deletion is usually "this agent is redundant", and the loss is noticed later. */
export function RetireAgentDialog({
  open,
  onOpenChange,
  agent,
  onRetire,
  isRetiring,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agent: Agent;
  onRetire: () => Promise<void>;
  isRetiring: boolean;
}) {
  const { agents } = useAgents();
  const { carryOver } = useAgentMemory(agent.id);
  const [selected, setSelected] = useState<string[]>([]);

  const canCarryOver = agent.allowedActions.includes("agent.memory.read");
  const destinations = agents.filter(
    (a) => a.id !== agent.id && a.allowedActions.includes("agent.memory.manage"),
  );

  const toggle = (id: string) =>
    setSelected((current) => (current.includes(id) ? current.filter((x) => x !== id) : [...current, id]));

  const confirm = async () => {
    if (selected.length > 0) {
      // Copy before deleting, and abort if it fails: proceeding would erase the
      // memory this step exists to save.
      try {
        const result = await carryOver.mutateAsync(selected);
        const failed = result.results.filter((r) => !r.shared);
        if (failed.length > 0) {
          toastError(new Error("Could not copy this agent's memory. Nothing has been deleted."));
          return;
        }
        toast.success(
          result.truncated
            ? `Copied the most recent ${result.copied} memories`
            : `Copied ${result.copied} ${result.copied === 1 ? "memory" : "memories"}`,
        );
      } catch (error) {
        toastError(error, "Could not copy this agent's memory. Nothing has been deleted.");
        return;
      }
    }
    await onRetire();
  };

  const busy = isRetiring || carryOver.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Retire {agent.name}?</DialogTitle>
          <DialogDescription>
            This removes the agent and everything it holds, including what it has learned. It cannot be
            undone.
          </DialogDescription>
        </DialogHeader>

        {canCarryOver && destinations.length > 0 && (
          <div className="space-y-2">
            <Label>Keep what it learned (optional)</Label>
            <p className="text-xs" style={{ color: "var(--ink-4)" }}>
              Pick agents to copy its memory into before it is deleted.
            </p>
            <div
              className="max-h-48 divide-y overflow-y-auto rounded-lg"
              style={{ background: "var(--bg-elev)", border: "1px solid var(--line)" }}
              role="group"
              aria-label="Agents to copy memory into"
            >
              {destinations.map((candidate) => {
                const isSelected = selected.includes(candidate.id);
                return (
                  <button
                    key={candidate.id}
                    type="button"
                    onClick={() => toggle(candidate.id)}
                    aria-pressed={isSelected}
                    disabled={busy}
                    className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors duration-150 hover:bg-[var(--bg-soft)] disabled:opacity-50"
                  >
                    <AgentAvatar agent={candidate} size="sm" />
                    <span className="min-w-0 flex-1 truncate text-sm" style={{ color: "var(--ink)" }}>
                      {candidate.name}
                    </span>
                    <span
                      className="flex size-5 shrink-0 items-center justify-center rounded-full transition-colors duration-150"
                      style={
                        isSelected
                          ? { background: "var(--accent-color)", color: "#fff" }
                          : { border: "1px solid var(--line-strong)" }
                      }
                    >
                      {isSelected && <Check size={13} aria-hidden />}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button
            onClick={() => void confirm()}
            disabled={busy}
            style={{ background: "var(--err)", color: "#fff" }}
          >
            {carryOver.isPending ? "Copying memory…" : isRetiring ? "Retiring…" : "Retire agent"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
