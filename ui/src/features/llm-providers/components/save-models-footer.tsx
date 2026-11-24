"use client";

import { Loader2 } from "lucide-react";

import { DialogFooter } from "@/components/ui/dialog";

import { failureMessage } from "../utils";

export function SaveModelsFooter({
  error,
  isSaving,
  disabled,
  onCancel,
  onSave,
}: {
  error: unknown;
  isSaving: boolean;
  disabled: boolean;
  onCancel: () => void;
  onSave: () => void;
}) {
  return (
    <>
      {error ? (
        <p className="m-0 text-[0.8rem]" style={{ color: "var(--err)" }} role="alert">
          {failureMessage(error)}
        </p>
      ) : null}
      <DialogFooter>
        <button type="button" className="af-btn" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="af-btn af-btn-primary" disabled={disabled || isSaving} onClick={onSave}>
          {isSaving && <Loader2 size={14} className="animate-spin" />} Save models
        </button>
      </DialogFooter>
    </>
  );
}
