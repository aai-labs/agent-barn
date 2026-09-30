"use client";

import { Trash2 } from "lucide-react";
import { toast } from "sonner";

import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { toastError } from "@/shared/toast";

import { useDeleteTemplate } from "../hooks/use-delete-template";
import type { TemplateRead } from "../schemas";

interface DeleteTemplateDialogProps {
  template: TemplateRead | null;
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
    deleteTemplate.mutate(template.templateKey, {
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
    <ConfirmationDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Delete template?"
      description={
        <>
          This permanently deletes every version of{" "}
          <strong>{template?.templateName}</strong>. This action cannot be undone.
        </>
      }
      confirmLabel="Delete template"
      pendingLabel="Deleting…"
      onConfirm={handleDelete}
      isPending={deleteTemplate.isPending}
      variant="destructive"
      icon={<Trash2 size={18} />}
    />
  );
}
