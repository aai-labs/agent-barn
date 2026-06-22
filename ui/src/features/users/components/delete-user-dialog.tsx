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

import { useDeleteUser } from "../hooks/use-delete-user";
import type { UserRead } from "../schemas";

interface DeleteUserDialogProps {
  user: UserRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function DeleteUserDialog({ user, open, onOpenChange }: DeleteUserDialogProps) {
  const deleteUser = useDeleteUser();

  const handleDelete = () => {
    if (!user) return;
    deleteUser.mutate(user.id, {
      onSuccess: () => {
        toast.success("User deleted successfully");
        onOpenChange(false);
      },
      onError: (error) => {
        toast.error(error.message || "Failed to delete user");
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete user</DialogTitle>
          <DialogDescription>This action cannot be undone.</DialogDescription>
        </DialogHeader>

        <p className="text-[14px]" style={{ color: "var(--ink-2)" }}>
          Are you sure you want to delete <strong>{user?.email}</strong>? This action cannot be undone.
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
            disabled={deleteUser.isPending}
          >
            {deleteUser.isPending ? "Deleting…" : "Delete"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
