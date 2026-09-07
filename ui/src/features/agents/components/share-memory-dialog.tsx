"use client";

import { useState } from "react";
import { Check, Search } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { toastError } from "@/shared/toast";

import { useAgents } from "../hooks/use-agents";
import type { SharedFactResult } from "../schemas";
import { AgentAvatar } from "./agent-avatar";

type ShareMutation = {
  mutateAsync: (input: { content: string; targetAgentIds: string[] }) => Promise<SharedFactResult>;
  isPending: boolean;
};

/** Copies one fact into other agents' memory.
 *
 *  Honcho isolates workspaces at the schema level — `workspace_name` is part of
 *  nearly every composite key — so there is no cross-workspace read to grant and
 *  nothing here is a live link. This writes a copy; the destination keeps it even
 *  if this agent later forgets or is deleted. */
export function ShareMemoryDialog({
  open,
  onOpenChange,
  sourceAgentId,
  initialContent,
  share,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sourceAgentId: string;
  initialContent: string;
  share: ShareMutation;
}) {
  const { agents, isLoading } = useAgents();
  const [content, setContent] = useState(initialContent);
  const [selected, setSelected] = useState<string[]>([]);
  const [filter, setFilter] = useState("");

  const destinations = agents
    .filter((agent) => agent.id !== sourceAgentId)
    .filter((agent) => agent.name.toLowerCase().includes(filter.trim().toLowerCase()));

  const toggle = (agentId: string) =>
    setSelected((current) =>
      current.includes(agentId) ? current.filter((id) => id !== agentId) : [...current, agentId],
    );

  const onShare = async () => {
    try {
      const result = await share.mutateAsync({ content, targetAgentIds: selected });
      // Per-destination results: one agent failing does not mean the others did,
      // so report both halves rather than a single success or failure.
      const shared = result.results.filter((r) => r.shared);
      const failed = result.results.filter((r) => !r.shared);
      if (shared.length > 0) {
        toast.success(`Shared with ${shared.length} ${shared.length === 1 ? "agent" : "agents"}`);
      }
      if (failed.length > 0) {
        toastError(new Error(`Could not share with ${failed.length} of ${result.results.length} agents`));
      }
      if (failed.length === 0) {
        onOpenChange(false);
        setSelected([]);
      }
    } catch (error) {
      toastError(error);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Share this memory</DialogTitle>
          <DialogDescription>
            The agents you pick will remember this too. They keep it even if this agent forgets it later.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="shared-fact-content">Fact</Label>
            <Textarea
              id="shared-fact-content"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={3}
            />
            <p className="text-xs" style={{ color: "var(--ink-4)" }}>
              Reword it if it only makes sense in this agent&apos;s context.
            </p>
          </div>

          <div className="space-y-2">
            <div className="flex items-baseline justify-between">
              <Label>Share with</Label>
              {selected.length > 0 && (
                <span className="text-xs" style={{ color: "var(--ink-3)" }}>
                  {selected.length} selected
                </span>
              )}
            </div>

            {isLoading ? (
              <div className="space-y-2 rounded-lg p-3" style={{ border: "1px solid var(--line)" }}>
                {Array.from({ length: 3 }, (_, i) => (
                  <Skeleton key={i} className="h-9 w-full" />
                ))}
              </div>
            ) : agents.length <= 1 ? (
              <div
                className="rounded-lg px-4 py-8 text-center text-sm"
                style={{ background: "var(--bg-soft)", border: "1px dashed var(--line-strong)", color: "var(--ink-3)" }}
              >
                No other agents in this organization to share with.
              </div>
            ) : (
              <>
                {agents.length > 6 && (
                  <div className="relative">
                    <Search
                      size={14}
                      aria-hidden
                      className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2"
                      style={{ color: "var(--ink-4)" }}
                    />
                    <Input
                      value={filter}
                      onChange={(e) => setFilter(e.target.value)}
                      placeholder="Filter agents…"
                      aria-label="Filter agents"
                      className="pl-9"
                    />
                  </div>
                )}
                <div
                  className="max-h-60 divide-y overflow-y-auto rounded-lg"
                  style={{ background: "var(--bg-elev)", border: "1px solid var(--line)" }}
                  role="group"
                  aria-label="Agents to share with"
                >
                  {destinations.length === 0 ? (
                    <p className="px-4 py-6 text-center text-sm" style={{ color: "var(--ink-3)" }}>
                      No agents match “{filter}”.
                    </p>
                  ) : (
                    destinations.map((agent) => {
                      const isSelected = selected.includes(agent.id);
                      return (
                        <button
                          key={agent.id}
                          type="button"
                          onClick={() => toggle(agent.id)}
                          aria-pressed={isSelected}
                          className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors duration-150 hover:bg-[var(--bg-soft)]"
                        >
                          <AgentAvatar agent={agent} size="sm" />
                          <span className="min-w-0 flex-1 truncate text-sm" style={{ color: "var(--ink)" }}>
                            {agent.name}
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
                    })
                  )}
                </div>
              </>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => void onShare()}
            disabled={share.isPending || selected.length === 0 || content.trim().length === 0}
          >
            {share.isPending
              ? "Sharing…"
              : selected.length > 0
                ? `Share with ${selected.length} ${selected.length === 1 ? "agent" : "agents"}`
                : "Share"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
