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

import { useCreateOrganization } from "../hooks/use-organization-actions";
import {
  type CreateOrganizationFormData,
  CreateOrganizationFormSchema,
  type OrganizationCreateResult,
} from "../schemas";
import { InviteLinkField } from "./invite-link-field";

interface CreateOrganizationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateOrganizationDialog({
  open,
  onOpenChange,
}: CreateOrganizationDialogProps) {
  const createOrganization = useCreateOrganization();
  const [result, setResult] = useState<OrganizationCreateResult | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<CreateOrganizationFormData>({
    resolver: zodResolver(CreateOrganizationFormSchema),
    defaultValues: { name: "", description: "", ownerEmail: "", ownerName: "" },
  });

  const resetAll = () => {
    reset();
    setResult(null);
  };

  const onSubmit = (values: CreateOrganizationFormData) => {
    createOrganization.mutate(values, {
      onSuccess: (created) => {
        setResult(created);
        reset();
        toast.success(
          created.inviteLink
            ? "Organization created and invite sent."
            : "Organization created.",
        );
      },
      onError: (error) => {
        toast.error(error.message || "Failed to create organization");
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
          <DialogTitle>
            {result ? "Organization created" : "Create organization"}
          </DialogTitle>
          <DialogDescription>
            {result
              ? `${result.organization.name} is ready. The owner has been invited.`
              : "Create a new organization and invite its first owner by email."}
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <div className="flex flex-col gap-4">
            <p className="text-[13.5px]" style={{ color: "var(--ink-2)" }}>
              An invite was sent to{" "}
              <span style={{ color: "var(--ink)" }}>
                {result.organization.ownerEmail}
              </span>
              . They&apos;ll set their password to activate the account.
            </p>
            {result.inviteLink && (
              <InviteLinkField link={result.inviteLink} label="Owner invite link" />
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
                htmlFor="name"
                className="mb-1.5 block text-[13.5px] font-medium"
                style={{ color: "var(--ink)" }}
              >
                Name
              </label>
              <input
                id="name"
                type="text"
                placeholder="Acme Inc"
                className="af-input"
                aria-invalid={!!errors.name}
                {...register("name")}
              />
              {errors.name && (
                <p className="mt-1 text-[12.5px]" style={{ color: "var(--err)" }}>
                  {errors.name.message}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="description"
                className="mb-1.5 block text-[13.5px] font-medium"
                style={{ color: "var(--ink)" }}
              >
                Description{" "}
                <span className="font-normal" style={{ color: "var(--ink-4)" }}>
                  (optional)
                </span>
              </label>
              <input
                id="description"
                type="text"
                placeholder="What this organization is for"
                className="af-input"
                {...register("description")}
              />
            </div>

            <div>
              <label
                htmlFor="ownerEmail"
                className="mb-1.5 block text-[13.5px] font-medium"
                style={{ color: "var(--ink)" }}
              >
                Owner email
              </label>
              <input
                id="ownerEmail"
                type="email"
                placeholder="owner@acme.com"
                className="af-input"
                aria-invalid={!!errors.ownerEmail}
                {...register("ownerEmail")}
              />
              {errors.ownerEmail && (
                <p className="mt-1 text-[12.5px]" style={{ color: "var(--err)" }}>
                  {errors.ownerEmail.message}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="ownerName"
                className="mb-1.5 block text-[13.5px] font-medium"
                style={{ color: "var(--ink)" }}
              >
                Owner name{" "}
                <span className="font-normal" style={{ color: "var(--ink-4)" }}>
                  (optional)
                </span>
              </label>
              <input
                id="ownerName"
                type="text"
                placeholder="Jane Doe"
                className="af-input"
                {...register("ownerName")}
              />
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
                disabled={createOrganization.isPending}
              >
                {createOrganization.isPending ? "Creating…" : "Create"}
              </button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
