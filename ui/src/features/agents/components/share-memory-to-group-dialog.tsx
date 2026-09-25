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
import { Skeleton } from "@/components/ui/skeleton";
import { useMemoryGroups } from "@/features/memory-groups/hooks/use-memory-groups";
import type { ShareMemoryItemData, ShareMemoryItemResult } from "@/features/memory-groups/schemas";
import { toastError } from "@/shared/toast";

type ShareItemMutation = {
  mutateAsync: (input: ShareMemoryItemData) => Promise<ShareMemoryItemResult>;
  isPending: boolean;
};

/** Shares one memory item from this agent's group into other groups.
 *
 *  Within a group memory is already shared; this is the one path that crosses
 *  into another pool. It copies the item — each destination keeps its copy even
 *  if the source group later forgets it. */
export function ShareMemoryToGroupDialog({
  open,
  onOpenChange,
  sourceGroupId,
  memoryId,
  content,
  shareItem,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sourceGroupId: string;
  memoryId: string;
  content: string;
  shareItem: ShareItemMutation;
}) {
  const { groups, isLoading } = useMemoryGroups();
  const [selected, setSelected] = useState<string[]>([]);

  const destinations = groups.filter((group) => group.id !== sourceGroupId);

  const toggle = (groupId: string) =>
    setSelected((current) =>
      current.includes(groupId) ? current.filter((id) => id !== groupId) : [...current, groupId],
    );

  const onShare = async () => {
    try {
      const result = await shareItem.mutateAsync({ sourceGroupId, memoryId, targetGroupIds: selected });
      // Per-destination results: one group failing does not mean the others did.
      const shared = result.results.filter((r) => r.shared);
      const failed = result.results.filter((r) => !r.shared);
      if (shared.length > 0) {
        toast.success(`Shared with ${shared.length} ${shared.length === 1 ? "group" : "groups"}`);
      }
      if (failed.length > 0) {
        toastError(new Error(`Could not share with ${failed.length} of ${result.results.length} groups`));
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
          <DialogTitle>Share with another group</DialogTitle>
          <DialogDescription>
            The groups you pick will remember this too. They keep it even if this group forgets it later.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          <div className="space-y-2">
            <Label>Memory</Label>
            <p
              className="rounded-lg px-3 py-2.5 text-sm"
              style={{ background: "var(--bg-soft)", border: "1px solid var(--line)", color: "var(--ink-2)" }}
            >
              {content}
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
            ) : destinations.length === 0 ? (
              <div
                className="rounded-lg px-4 py-8 text-center text-sm"
                style={{ background: "var(--bg-soft)", border: "1px dashed var(--line-strong)", color: "var(--ink-3)" }}
              >
                No other groups in this organization to share with.
              </div>
            ) : (
              <div
                className="max-h-60 divide-y overflow-y-auto rounded-lg"
                style={{ background: "var(--bg-elev)", border: "1px solid var(--line)" }}
                role="group"
                aria-label="Groups to share with"
              >
                {destinations.map((group) => {
                  const isSelected = selected.includes(group.id);
                  return (
                    <button
                      key={group.id}
                      type="button"
                      onClick={() => toggle(group.id)}
                      aria-pressed={isSelected}
                      className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors duration-150 hover:bg-[var(--bg-soft)]"
                    >
                      <span className="min-w-0 flex-1 truncate text-sm" style={{ color: "var(--ink)" }}>
                        {group.name}
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
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => void onShare()} disabled={shareItem.isPending || selected.length === 0}>
            {shareItem.isPending
              ? "Sharing…"
              : selected.length > 0
                ? `Share with ${selected.length} ${selected.length === 1 ? "group" : "groups"}`
                : "Share"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
