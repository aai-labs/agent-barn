"use client";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

import type { LlmProviderConnection } from "../schemas";
import { providerTitle } from "../utils";
import { connectionSubtitle } from "./provider-card";

const ACTION_CLASS = "af-btn w-full justify-start";

export function ManageProviderDialog({
  connection,
  open,
  onOpenChange,
  onModels,
  onReplaceKey,
  onDelete,
}: {
  connection: LlmProviderConnection;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onModels: () => void;
  onReplaceKey: () => void;
  onDelete: () => void;
}) {
  function choose(action: () => void) {
    onOpenChange(false);
    action();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Manage {providerTitle(connection)}</DialogTitle>
          <DialogDescription className="break-all">{connectionSubtitle(connection)}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          {connection.hasApiKey && (
            <button type="button" className={ACTION_CLASS} onClick={() => choose(onModels)}>
              Models
            </button>
          )}
          <button type="button" className={ACTION_CLASS} onClick={() => choose(onReplaceKey)}>
            {connection.hasApiKey ? "Replace key" : "Save a key"}
          </button>
          <button
            type="button"
            className={ACTION_CLASS}
            style={{ color: "var(--err)" }}
            onClick={() => choose(onDelete)}
          >
            Delete
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
