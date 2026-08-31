"use client";

import type { ReactNode } from "react";
import { useState } from "react";
import { Pencil } from "lucide-react";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { toastError } from "@/shared/toast";

export type SettingsSectionConfirmCopy = {
  title: string;
  description: ReactNode;
};

const DEFAULT_CONFIRM: SettingsSectionConfirmCopy = {
  title: "Apply changes?",
  description: "This saves the changes you made in this section.",
};

/**
 * One card on a settings surface: a body, an optional footer, and the
 * Edit → dirty → Apply → confirm flow shared by every section that can be edited.
 *
 * `title` and `description` are not rendered here. The surrounding page renders the
 * visible heading pair from its section registry, so this component exposes them as
 * `aria-label` and `data-section-description` instead — assistive tech and tests can
 * identify a section without the page duplicating its own heading inside the card.
 */
export function SettingsSection({
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
  applyLabel = "Apply",
  applyPendingLabel = "Applying…",
  actionsRenderer,
  unstyled = false,
  confirm = DEFAULT_CONFIRM,
  errorsShownInline = false,
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
  /** Names the consequence, not the mechanism — "Apply & Restart" when a runtime cycles. */
  applyLabel?: string;
  applyPendingLabel?: string;
  /** Render the edit/apply actions at a caller-owned location. */
  actionsRenderer?: (actions: ReactNode) => ReactNode;
  /** Omit the standard card frame when the caller owns the layout. */
  unstyled?: boolean;
  /** What the confirmation dialog says this Apply will do. */
  confirm?: SettingsSectionConfirmCopy;
  /**
   * Set when the body renders the failure itself. A rejected Apply is then stated once,
   * next to the control that caused it, instead of also being thrown as a toast.
   */
  errorsShownInline?: boolean;
  children: ReactNode;
}) {
  const [applyConfirmationOpen, setApplyConfirmationOpen] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const isEditing = editing && canEdit;
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
      {isApplying ? applyPendingLabel : applyLabel}
    </button>
  ) : null;
  const hasFooter = Boolean(footer || editAction || applyAction);
  const renderedContent = actionsRenderer
    ? actionsRenderer(
        <div className="flex flex-wrap items-center justify-end gap-2">
          {editAction}
          {applyAction}
        </div>,
      )
    : (
        <>
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
        </>
      );

  async function confirmApply() {
    if (!onApply) return;
    setIsApplying(true);
    try {
      await onApply();
      setApplyConfirmationOpen(false);
      onApplied?.();
    } catch (error) {
      setApplyConfirmationOpen(false);
      if (!errorsShownInline) toastError(error);
    } finally {
      setIsApplying(false);
    }
  }

  const content = unstyled ? (
    renderedContent
  ) : (
    <section
      className="af-card overflow-hidden"
      aria-label={title}
      data-section-description={description}
    >
      {renderedContent}
    </section>
  );

  return (
    <>
      {content}
      <ConfirmationDialog
        open={applyConfirmationOpen}
        onOpenChange={setApplyConfirmationOpen}
        title={confirm.title}
        description={confirm.description}
        confirmLabel={applyLabel}
        pendingLabel={applyPendingLabel}
        onConfirm={() => void confirmApply()}
        isPending={isApplying}
      />
    </>
  );
}
