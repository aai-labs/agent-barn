"use client";

import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { CheckIcon, CopyIcon, Loader2Icon, UserPlusIcon } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";

import { useCreateUser } from "../hooks/use-create-user";
import {
  type PlatformUserCreateForm,
  type PlatformUserCreateResult,
  PlatformUserCreateFormSchema,
} from "../schemas";

interface CreateUserDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateUserDialog({ open, onOpenChange }: CreateUserDialogProps) {
  const [created, setCreated] = useState<PlatformUserCreateResult | null>(null);
  const createUser = useCreateUser();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<PlatformUserCreateForm>({
    resolver: zodResolver(PlatformUserCreateFormSchema),
    defaultValues: { email: "", fullName: "", organizationName: "" },
  });

  const resetDialog = () => {
    reset();
    setCreated(null);
  };

  const closeDialog = () => {
    resetDialog();
    onOpenChange(false);
  };

  const onSubmit = (values: PlatformUserCreateForm) => {
    createUser.mutate(values, {
      onSuccess: (result) => {
        setCreated(result);
        toast.success("User and initial organization created");
      },
      onError: (error) => {
        toast.error(error.message || "Failed to create user");
      },
    });
  };

  const copyInvite = async () => {
    if (!created) return;
    await navigator.clipboard.writeText(created.inviteLink);
    toast.success("Invitation link copied");
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) resetDialog();
        onOpenChange(nextOpen);
      }}
    >
      <DialogContent>
        {created ? (
          <>
            <DialogHeader>
              <DialogTitle>Invitation created</DialogTitle>
              <DialogDescription>
                {created.user.email} is the owner of {created.organization.name}. An
                invitation was sent so they can set their password.
              </DialogDescription>
            </DialogHeader>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="created-user-invite">Invitation link</FieldLabel>
                <Input
                  id="created-user-invite"
                  value={created.inviteLink}
                  readOnly
                />
                <FieldDescription>
                  Copy this link if email delivery is unavailable.
                </FieldDescription>
              </Field>
            </FieldGroup>
            <DialogFooter>
              <button
                type="button"
                className="af-btn"
                onClick={() => void copyInvite()}
              >
                <CopyIcon width={15} height={15} /> Copy link
              </button>
              <button
                type="button"
                className="af-btn af-btn-primary"
                onClick={closeDialog}
              >
                <CheckIcon width={15} height={15} /> Done
              </button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Create user</DialogTitle>
              <DialogDescription>
                Create a pending account and its initial organization. The user will
                receive an invitation to set their own password.
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
              <FieldGroup>
                <Field data-invalid={!!errors.email}>
                  <FieldLabel htmlFor="new-user-email">Email</FieldLabel>
                  <Input
                    id="new-user-email"
                    type="email"
                    placeholder="user@example.com"
                    aria-invalid={!!errors.email}
                    {...register("email")}
                  />
                  <FieldError errors={[errors.email]} />
                </Field>
                <Field data-invalid={!!errors.fullName}>
                  <FieldLabel htmlFor="new-user-full-name">Full name</FieldLabel>
                  <Input
                    id="new-user-full-name"
                    placeholder="Jane Doe"
                    aria-invalid={!!errors.fullName}
                    {...register("fullName")}
                  />
                  <FieldDescription>Optional.</FieldDescription>
                  <FieldError errors={[errors.fullName]} />
                </Field>
                <Field data-invalid={!!errors.organizationName}>
                  <FieldLabel htmlFor="new-user-organization-name">
                    Initial organization name
                  </FieldLabel>
                  <Input
                    id="new-user-organization-name"
                    placeholder="Jane Doe's Organization"
                    aria-invalid={!!errors.organizationName}
                    {...register("organizationName")}
                  />
                  <FieldDescription>
                    Optional. Organization names are display labels and do not need to
                    be globally unique.
                  </FieldDescription>
                  <FieldError errors={[errors.organizationName]} />
                </Field>
              </FieldGroup>
              <DialogFooter>
                <button
                  type="button"
                  className="af-btn"
                  onClick={closeDialog}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="af-btn af-btn-primary"
                  disabled={createUser.isPending}
                >
                  {createUser.isPending ? (
                    <Loader2Icon width={15} height={15} className="animate-spin" />
                  ) : (
                    <UserPlusIcon width={15} height={15} />
                  )}
                  Create and invite
                </button>
              </DialogFooter>
            </form>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
