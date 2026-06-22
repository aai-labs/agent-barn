"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { api } from "@/shared/api";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const ChangePasswordSchema = z
  .object({
    oldPassword: z.string().min(1, { message: "Old password is required" }),
    newPassword: z
      .string()
      .min(8, { message: "Password must be at least 8 characters" })
      .regex(/[A-Z]/, { message: "Must include at least one uppercase letter" })
      .regex(/[a-z]/, { message: "Must include at least one lowercase letter" })
      .regex(/[0-9]/, { message: "Must include at least one number" }),
    confirmNewPassword: z.string().min(1, { message: "Confirm your new password" }),
  })
  .refine((data) => data.newPassword === data.confirmNewPassword, {
    message: "Passwords do not match",
    path: ["confirmNewPassword"],
  });

type ChangePasswordData = z.infer<typeof ChangePasswordSchema>;

interface ChangePasswordDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ChangePasswordDialog({ open, onOpenChange }: ChangePasswordDialogProps) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ChangePasswordData>({
    resolver: zodResolver(ChangePasswordSchema),
    defaultValues: { oldPassword: "", newPassword: "", confirmNewPassword: "" },
  });

  const onSubmit = async (values: ChangePasswordData) => {
    try {
      await api.post("/api/v1/auth/me/change-password", {
        old_password: values.oldPassword,
        new_password: values.newPassword,
      });
      toast.success("Password changed successfully");
      reset();
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to change password");
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) reset();
        onOpenChange(v);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Change password</DialogTitle>
          <DialogDescription>Update your account password.</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
          <div>
            <label htmlFor="oldPassword" className="block font-medium text-[13.5px] mb-1.5" style={{ color: "var(--ink)" }}>
              Old password
            </label>
            <input
              id="oldPassword"
              type="password"
              className="af-input"
              aria-invalid={!!errors.oldPassword}
              {...register("oldPassword")}
            />
            {errors.oldPassword && (
              <p className="text-[12.5px] mt-1" style={{ color: "var(--err)" }}>
                {errors.oldPassword.message}
              </p>
            )}
          </div>

          <div>
            <label htmlFor="newPassword" className="block font-medium text-[13.5px] mb-1.5" style={{ color: "var(--ink)" }}>
              New password
            </label>
            <input
              id="newPassword"
              type="password"
              className="af-input"
              aria-invalid={!!errors.newPassword}
              {...register("newPassword")}
            />
            {errors.newPassword && (
              <p className="text-[12.5px] mt-1" style={{ color: "var(--err)" }}>
                {errors.newPassword.message}
              </p>
            )}
          </div>

          <div>
            <label htmlFor="confirmNewPassword" className="block font-medium text-[13.5px] mb-1.5" style={{ color: "var(--ink)" }}>
              Confirm new password
            </label>
            <input
              id="confirmNewPassword"
              type="password"
              className="af-input"
              aria-invalid={!!errors.confirmNewPassword}
              {...register("confirmNewPassword")}
            />
            {errors.confirmNewPassword && (
              <p className="text-[12.5px] mt-1" style={{ color: "var(--err)" }}>
                {errors.confirmNewPassword.message}
              </p>
            )}
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
              disabled={isSubmitting}
            >
              {isSubmitting ? "Changing…" : "Change password"}
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
