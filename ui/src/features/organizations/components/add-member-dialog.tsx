"use client";

import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
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

import { useMemberActions } from "../hooks/use-member-actions";
import {
  type AddMemberFormData,
  AddMemberFormSchema,
  type MemberInviteResult,
} from "../schemas";
import { InviteLinkField } from "./invite-link-field";

interface AddMemberDialogProps {
  organizationId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AddMemberDialog({
  organizationId,
  open,
  onOpenChange,
}: AddMemberDialogProps) {
  const { addMember } = useMemberActions(organizationId);
  const [result, setResult] = useState<MemberInviteResult | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<AddMemberFormData>({
    resolver: zodResolver(AddMemberFormSchema),
    defaultValues: { email: "", fullName: "", role: "MEMBER" },
  });

  const resetAll = () => {
    reset();
    setResult(null);
  };

  const onSubmit = (values: AddMemberFormData) => {
    addMember.mutate(values, {
      onSuccess: (created) => {
        setResult(created);
        reset();
        toast.success(
          created.inviteLink ? "Member invited." : "Member added.",
        );
      },
      onError: (error) => {
        toast.error(error.message || "Failed to add member");
      },
    });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) resetAll();
        onOpenChange(v);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{result ? "Member invited" : "Add member"}</DialogTitle>
          <DialogDescription>
            {result
              ? `${result.member.email} has been added as ${result.member.role.toLowerCase()}.`
              : "Invite someone to this organization by email."}
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <div className="flex flex-col gap-4">
            {result.inviteLink && (
              <InviteLinkField link={result.inviteLink} label="Invite link" />
            )}
            <DialogFooter>
              <button
                type="button"
                className="af-btn af-btn-primary"
                onClick={() => onOpenChange(false)}
              >
                Done
              </button>
            </DialogFooter>
          </div>
        ) : (
          <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
            <div>
              <label
                htmlFor="email"
                className="mb-1.5 block text-[13.5px] font-medium"
                style={{ color: "var(--ink)" }}
              >
                Email
              </label>
              <input
                id="email"
                type="email"
                placeholder="teammate@example.com"
                className="af-input"
                aria-invalid={!!errors.email}
                {...register("email")}
              />
              {errors.email && (
                <p className="mt-1 text-[12.5px]" style={{ color: "var(--err)" }}>
                  {errors.email.message}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="fullName"
                className="mb-1.5 block text-[13.5px] font-medium"
                style={{ color: "var(--ink)" }}
              >
                Full name{" "}
                <span className="font-normal" style={{ color: "var(--ink-4)" }}>
                  (optional)
                </span>
              </label>
              <input
                id="fullName"
                type="text"
                placeholder="Jane Doe"
                className="af-input"
                {...register("fullName")}
              />
            </div>

            <div>
              <label
                htmlFor="role"
                className="mb-1.5 block text-[13.5px] font-medium"
                style={{ color: "var(--ink)" }}
              >
                Role
              </label>
              <select id="role" className="af-select" {...register("role")}>
                <option value="MEMBER">Member</option>
                <option value="ADMIN">Admin</option>
              </select>
            </div>

            <DialogFooter>
              <button
                type="button"
                className="af-btn"
                onClick={() => onOpenChange(false)}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="af-btn af-btn-primary"
                disabled={addMember.isPending}
              >
                {addMember.isPending ? "Adding…" : "Add member"}
              </button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
