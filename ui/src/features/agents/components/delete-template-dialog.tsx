"use client";

import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toastError } from "@/shared/toast";

import { useDeleteTemplate } from "../hooks/use-delete-template";
import type { AgentTemplateRead } from "../schemas";

interface DeleteTemplateDialogProps {
  template: AgentTemplateRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted?: () => void;
}

export function DeleteTemplateDialog({
  template,
  open,
  onOpenChange,
  onDeleted,
}: DeleteTemplateDialogProps) {
  const deleteTemplate = useDeleteTemplate();

  const handleDelete = () => {
    if (!template) return;
    deleteTemplate.mutate(template.templateSlug, {
      onSuccess: () => {
        toast.success("Template deleted");
        onOpenChange(false);
        onDeleted?.();
      },
      onError: (error) => {
        toastError(error, "Failed to delete template");
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete template</DialogTitle>
          <DialogDescription>This action cannot be undone.</DialogDescription>
        </DialogHeader>

        <p className="text-[14px]" style={{ color: "var(--ink-2)" }}>
          Are you sure you want to delete <strong>{template?.templateName}</strong>?
          This permanently deletes all versions of this template.
        </p>

        <DialogFooter>
          <button
            type="button"
            className="af-btn"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </button>
          <button
            type="button"
            className="af-btn af-btn-danger"
            onClick={handleDelete}
            disabled={deleteTemplate.isPending}
          >
            {deleteTemplate.isPending ? "Deleting…" : "Delete"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
