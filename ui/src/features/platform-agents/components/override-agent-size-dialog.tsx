"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAgentSizes } from "@/features/agent-sizes/hooks/use-agent-sizes";
import { describeSize } from "@/features/agent-sizes/utils";

import { useSetPlatformAgentSize } from "../hooks/use-set-platform-agent-size";
import type { PlatformAgent } from "../schemas";

/**
 * Give one Agent a size from the catalog, or clear an override it has.
 *
 * Any enabled size can be set, whether or not the Agent's Organization may choose it. Setting
 * one locks the size for the Organization; clearing puts the Agent back on the default and
 * hands the choice back. Neither restarts the Agent.
 */
export function OverrideAgentSizeDialog({
  agent,
  open,
  onOpenChange,
}: {
  agent: PlatformAgent;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { sizes, isLoadingSizes } = useAgentSizes();
  const setSize = useSetPlatformAgentSize();
  const enabled = sizes.filter((size) => size.enabled);
  const [selected, setSelected] = useState<string>(agent.agentSize.id);
  const failure = setSize.error instanceof Error ? setSize.error.message : null;
  const unchanged = agent.agentSizeSetByPlatform && agent.agentSizeId === selected;

  const apply = (agentSizeId: string | null) =>
    setSize.mutate(
      { agentId: agent.id, agentSizeId },
      {
        onSuccess: (updated) => {
          toast.success(
            agentSizeId === null
              ? `${updated.name} is back on the default spec`
              : updated.pendingSize
                ? `${updated.name} moves to ${updated.agentSize.name} when it restarts`
                : `${updated.name} will start on ${updated.agentSize.name}`,
          );
          onOpenChange(false);
        },
      },
    );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[28rem]" data-testid="override-agent-size-dialog">
        <DialogHeader>
          <DialogTitle>Agent spec for {agent.name}</DialogTitle>
          <DialogDescription>
            {agent.organizationName} can&apos;t change a spec set here until you clear it. The Agent keeps
            running; the spec applies the next time it starts.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            apply(selected);
          }}
        >
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8rem] font-medium" style={{ color: "var(--ink-2)" }} htmlFor="override-size">
              Spec
            </label>
            <Select value={selected} onValueChange={setSelected} disabled={isLoadingSizes || setSize.isPending}>
              <SelectTrigger id="override-size" aria-label="Spec" className="w-full">
                <SelectValue placeholder={isLoadingSizes ? "Loading specs…" : "Choose a spec"} />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {enabled.map((size) => (
                    <SelectItem key={size.id} value={size.id}>
                      {describeSize(size)}
                      {size.isDefault ? " (default)" : ""}
                    </SelectItem>
                  ))}
                  {!enabled.some((size) => size.id === agent.agentSize.id) && (
                    <SelectItem value={agent.agentSize.id} disabled>
                      {describeSize(agent.agentSize)} (disabled)
                    </SelectItem>
                  )}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>

          {failure && (
            <p className="m-0 text-[0.8rem]" style={{ color: "var(--err)" }} role="alert">
              {failure}
            </p>
          )}

          <DialogFooter className="gap-2 sm:justify-between">
            {agent.agentSizeSetByPlatform ? (
              <button
                type="button"
                className="af-btn"
                disabled={setSize.isPending}
                onClick={() => apply(null)}
              >
                Clear override
              </button>
            ) : (
              <span />
            )}
            <div className="flex gap-2">
              <button type="button" className="af-btn" onClick={() => onOpenChange(false)}>
                Cancel
              </button>
              <button type="submit" className="af-btn af-btn-primary" disabled={setSize.isPending || unchanged}>
                {setSize.isPending && <Loader2 size={14} className="animate-spin" />} Set spec
              </button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
