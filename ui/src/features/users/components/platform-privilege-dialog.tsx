"use client";

import { useState } from "react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { usePlatformPrivilege } from "../hooks/use-platform-privilege";
import type { UserRead } from "../schemas";

interface PlatformPrivilegeDialogProps {
  user: UserRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function PlatformPrivilegeDialog({
  user,
  open,
  onOpenChange,
}: PlatformPrivilegeDialogProps) {
  const [reason, setReason] = useState("");
  const privilege = usePlatformPrivilege();
  const granting = !user?.isPlatformAdmin;

  const setOpen = (nextOpen: boolean) => {
    // Pin the dialog open while the mutation is in flight — otherwise Escape,
    // an outside click, or the header close button would dismiss it with no
    // visible sign the request is still running (it isn't cancelled either).
    if (privilege.isPending) return;
    if (!nextOpen) setReason("");
    onOpenChange(nextOpen);
  };

  const submit = () => {
    if (!user || reason.trim().length === 0) return;
    privilege.mutate(
      {
        userId: user.id,
        isPlatformAdmin: granting,
        reason: reason.trim(),
      },
      {
        onSuccess: () => {
          toast.success(
            granting
              ? `Platform Privilege granted to ${user.email}.`
              : `Platform Privilege revoked from ${user.email}.`,
          );
          setOpen(false);
        },
        onError: (error) => {
          toast.error(error.message || "Unable to change Platform Privilege.");
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {granting ? "Grant Platform Privilege" : "Revoke Platform Privilege"}
          </DialogTitle>
          <DialogDescription>
            {granting
              ? `${user?.email ?? "This user"} will be able to view platform-level user and organization lists and manage Platform Privilege.`
              : `${user?.email ?? "This user"} will lose platform-level authority on their next request.`}
          </DialogDescription>
        </DialogHeader>

        <div>
          <label
            htmlFor="platform-privilege-reason"
            className="mb-1.5 block text-[13.5px] font-medium"
            style={{ color: "var(--ink)" }}
          >
            Reason
          </label>
          <textarea
            id="platform-privilege-reason"
            className="af-input min-h-24 resize-y"
            maxLength={1000}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Why is this change needed?"
            disabled={privilege.isPending}
          />
          <p className="mt-1.5 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
            Required for the security audit record. Do not include passwords,
            tokens, API keys, or other secrets.
          </p>
        </div>

        <DialogFooter>
          <button
            type="button"
            className="af-btn"
            disabled={privilege.isPending}
            onClick={() => setOpen(false)}
          >
            Cancel
          </button>
          <button
            type="button"
            className="af-btn af-btn-primary"
            disabled={reason.trim().length === 0 || privilege.isPending}
            onClick={submit}
          >
            {privilege.isPending
              ? "Saving…"
              : granting
                ? "Grant privilege"
                : "Revoke privilege"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
