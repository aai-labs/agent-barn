"use client";

import type { ReactNode } from "react";
import { useState } from "react";
import { Pencil } from "lucide-react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { toastError } from "@/shared/toast";

export function AgentConfigurationSection({
  title,
  description,
  editing = false,
  canEdit = false,
  onEdit,
  footer,
  onApply,
  onCancel,
  onApplied,
  applyDisabled = false,
  restartOnApply = false,
  children,
}: {
  title: string;
  description: string;
  editing?: boolean;
  canEdit?: boolean;
  onEdit?: () => void;
  footer?: ReactNode;
  onApply?: () => void | Promise<void>;
  onCancel?: () => void;
  onApplied?: () => void;
  applyDisabled?: boolean;
  restartOnApply?: boolean;
  children: ReactNode;
}) {
  const [applyConfirmationOpen, setApplyConfirmationOpen] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const isEditing = editing && canEdit;
  const applyLabel = restartOnApply ? "Apply & Restart" : "Apply";
  const editAction = canEdit && onEdit ? (
    isEditing ? (
      <button type="button" className="af-btn" onClick={onCancel} disabled={isApplying}>
        Cancel
      </button>
    ) : (
      <button type="button" className="af-btn" onClick={onEdit}>
        <Pencil size={14} /> Edit
      </button>
    )
  ) : null;
  const applyAction = isEditing && onApply ? (
    <button
      type="button"
      className="af-btn af-btn-primary"
      disabled={applyDisabled || isApplying}
      onClick={() => setApplyConfirmationOpen(true)}
    >
      {isApplying ? (restartOnApply ? "Applying & Restarting…" : "Applying…") : applyLabel}
    </button>
  ) : null;
  const hasFooter = Boolean(footer || editAction || applyAction);

  async function confirmApply() {
    if (!onApply) return;
    setIsApplying(true);
    try {
      await onApply();
      setApplyConfirmationOpen(false);
      onApplied?.();
    } catch (error) {
      setApplyConfirmationOpen(false);
      toastError(error);
    } finally {
      setIsApplying(false);
    }
  }

  return (
    <section
      className="af-card overflow-hidden"
      aria-label={title}
      data-section-description={description}
    >
      <div className="p-5">{children}</div>
      {hasFooter && (
        <footer
          className="flex flex-wrap items-center justify-end gap-2 border-t px-5 py-3"
          style={{ borderColor: "var(--line)" }}
        >
          {footer}
          {editAction}
          {applyAction}
        </footer>
      )}
      <ConfirmationDialog
        open={applyConfirmationOpen}
        onOpenChange={setApplyConfirmationOpen}
        title={restartOnApply ? "Apply changes and restart the Agent?" : "Apply changes to the Agent?"}
        description={
          restartOnApply
            ? "This saves the changes, stops the Agent, and starts it again with the updated configuration."
            : "This saves the changes while keeping the Agent stopped. Start it from the Agent detail page when you are ready."
        }
        confirmLabel={applyLabel}
        pendingLabel={restartOnApply ? "Applying & Restarting…" : "Applying…"}
        onConfirm={() => void confirmApply()}
        isPending={isApplying}
      />
    </section>
  );
}
