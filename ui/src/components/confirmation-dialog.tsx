"use client";

import type { ReactNode } from "react";
import { Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export type ConfirmationDialogVariant = "default" | "destructive";

type ConfirmationDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description: ReactNode;
  confirmLabel: string;
  pendingLabel?: string;
  onConfirm: () => void | Promise<void>;
  isPending?: boolean;
  variant?: ConfirmationDialogVariant;
  icon?: ReactNode;
  children?: ReactNode;
};

export function ConfirmationDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  pendingLabel = "Confirming…",
  onConfirm,
  isPending = false,
  variant = "default",
  icon,
  children,
}: ConfirmationDialogProps) {
  const isDestructive = variant === "destructive";

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!isPending) onOpenChange(nextOpen);
      }}
    >
      <DialogContent
        className="max-w-md overflow-hidden rounded-2xl p-0 sm:rounded-2xl"
        showCloseButton={!isPending}
        style={{
          background: "var(--bg-elev)",
          borderColor: "var(--line)",
          boxShadow: "var(--shadow-pop)",
        }}
      >
        <div className="px-6 pt-6 pb-5">
          {icon && (
            <div
              className="mb-4 flex size-10 items-center justify-center rounded-xl"
              style={{
                background: isDestructive
                  ? "var(--err-soft)"
                  : "var(--accent-soft)",
                color: isDestructive ? "var(--err)" : "var(--accent-ink)",
              }}
            >
              {icon}
            </div>
          )}
          <DialogHeader className="gap-1">
            <DialogTitle
              className="text-[19px] font-semibold tracking-tight"
              style={{ color: "var(--ink)" }}
            >
              {title}
            </DialogTitle>
            <DialogDescription
              className="text-[13.5px] leading-[1.6]"
              style={{ color: "var(--ink-3)" }}
            >
              {description}
            </DialogDescription>
          </DialogHeader>
          {children}
        </div>

        <DialogFooter
          className="mt-0 border-t px-6 py-4"
          style={{ borderColor: "var(--line)" }}
        >
          <button
            type="button"
            className="af-btn"
            onClick={() => onOpenChange(false)}
            disabled={isPending}
          >
            Cancel
          </button>
          <button
            type="button"
            className={
              isDestructive ? "af-btn af-btn-danger" : "af-btn af-btn-primary"
            }
            onClick={() => void onConfirm()}
            disabled={isPending}
          >
            {isPending && <Loader2 size={14} className="animate-spin" />}
            {isPending ? pendingLabel : confirmLabel}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
