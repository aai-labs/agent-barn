"use client";

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

import { useUpdateOrganization } from "../hooks/use-organization-actions";
import {
  type Organization,
  type RenameOrganizationFormData,
  RenameOrganizationFormSchema,
} from "../schemas";

export function RenameOrganizationDialog({
  organization,
  onClose,
}: {
  organization: Organization;
  onClose: () => void;
}) {
  const updateOrganization = useUpdateOrganization();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<RenameOrganizationFormData>({
    resolver: zodResolver(RenameOrganizationFormSchema),
    defaultValues: { name: organization.name },
  });

  const onSubmit = (data: RenameOrganizationFormData) => {
    if (updateOrganization.isPending) return;
    updateOrganization.mutate(
      { organizationId: organization.id, data },
      {
        onSuccess: () => {
          toast.success("Organization renamed.");
          onClose();
        },
      },
    );
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !updateOrganization.isPending) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rename organization</DialogTitle>
          <DialogDescription>Update the name shown throughout your organization.</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
          <div>
            <label htmlFor="organization-name" className="mb-1.5 block text-[13.5px] font-medium">
              Organization name
            </label>
            <input
              id="organization-name"
              className="af-input w-full"
              disabled={updateOrganization.isPending}
              aria-invalid={!!errors.name}
              aria-describedby={errors.name ? "organization-name-error" : undefined}
              {...register("name")}
            />
            {errors.name && (
              <p id="organization-name-error" role="alert" className="mt-1 text-[12.5px]" style={{ color: "var(--err)" }}>
                {errors.name.message}
              </p>
            )}
          </div>
          <DialogFooter>
            <button type="button" className="af-btn" disabled={updateOrganization.isPending} onClick={onClose}>Cancel</button>
            <button type="submit" className="af-btn-primary" disabled={updateOrganization.isPending}>
              {updateOrganization.isPending ? "Saving…" : "Save name"}
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
