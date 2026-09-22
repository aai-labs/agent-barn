"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import type { Agent } from "../schemas";

/** Retiring an agent removes it and everything it privately owns. Its
 *  contributions to any shared memory group stay in the group — deleting an agent
 *  never erases a pool — so there is nothing to carry over first. */
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
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Retire {agent.name}?</DialogTitle>
          <DialogDescription>
            This removes the agent and everything it privately owns. Anything it contributed to a
            shared memory group stays in the group. This cannot be undone.
          </DialogDescription>
        </DialogHeader>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={isRetiring}>
            Cancel
          </Button>
          <Button
            onClick={() => void onRetire()}
            disabled={isRetiring}
            style={{ background: "var(--err)", color: "#fff" }}
          >
            {isRetiring ? "Retiring…" : "Retire agent"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
