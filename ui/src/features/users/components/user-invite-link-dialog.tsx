"use client";

import { CopyIcon } from "lucide-react";
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
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

interface UserInviteLinkDialogProps {
  email: string;
  inviteLink: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function UserInviteLinkDialog({
  email,
  inviteLink,
  open,
  onOpenChange,
}: UserInviteLinkDialogProps) {
  const copyInvite = async () => {
    await navigator.clipboard.writeText(inviteLink);
    toast.success("Invitation link copied");
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invitation resent</DialogTitle>
          <DialogDescription>
            A new invitation was sent to {email}. Any previous invitation link is now
            invalid.
          </DialogDescription>
        </DialogHeader>
        <Field>
          <FieldLabel htmlFor="resent-user-invite">Invitation link</FieldLabel>
          <Input id="resent-user-invite" value={inviteLink} readOnly />
          <FieldDescription>
            Copy this link if email delivery is unavailable.
          </FieldDescription>
        </Field>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => void copyInvite()}
          >
            <CopyIcon data-icon="inline-start" />
            Copy link
          </Button>
          <Button type="button" onClick={() => onOpenChange(false)}>
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
