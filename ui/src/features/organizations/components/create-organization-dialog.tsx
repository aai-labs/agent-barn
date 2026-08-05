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

import { useCreateOrganization } from "../hooks/use-organization-actions";
import {
  type CreateOrganizationFormData,
  CreateOrganizationFormSchema,
} from "../schemas";

interface CreateOrganizationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateOrganizationDialog({
  open,
  onOpenChange,
}: CreateOrganizationDialogProps) {
  const createOrganization = useCreateOrganization();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<CreateOrganizationFormData>({
    resolver: zodResolver(CreateOrganizationFormSchema),
    defaultValues: { name: "", description: "" },
  });

  const resetAll = () => {
    reset();
  };

  const onSubmit = (values: CreateOrganizationFormData) => {
    createOrganization.mutate(values, {
      onSuccess: (created) => {
        reset();
        onOpenChange(false);
        toast.success(`${created.name} created. You are its owner.`);
      },
      onError: (error) => {
        toast.error(error.message || "Failed to create organization.");
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
          <DialogTitle>Create organization</DialogTitle>
          <DialogDescription>
            You will become this organization&apos;s owner. New organizations use the
            platform&apos;s default model configuration.
          </DialogDescription>
        </DialogHeader>

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
      </DialogContent>
    </Dialog>
  );
}
