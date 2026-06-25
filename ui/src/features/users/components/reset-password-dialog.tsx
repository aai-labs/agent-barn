"use client";

import { useState } from "react";
import { Copy, Eye, EyeOff, RefreshCw } from "lucide-react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { strongPasswordSchema } from "@/auth/schemas";

import { useResetUserPassword } from "../hooks/use-reset-user-password";
import type { UserRead } from "../schemas";
import { generateStrongPassword } from "../utils";

const ResetPasswordSchema = z.object({
  newPassword: strongPasswordSchema,
});

type ResetPasswordData = z.infer<typeof ResetPasswordSchema>;

interface ResetPasswordDialogProps {
  user: UserRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ResetPasswordDialog({ user, open, onOpenChange }: ResetPasswordDialogProps) {
  const [showPassword, setShowPassword] = useState(false);
  const resetPassword = useResetUserPassword();

  const {
    register,
    handleSubmit,
    setValue,
    reset,
    formState: { errors },
  } = useForm<ResetPasswordData>({
    resolver: zodResolver(ResetPasswordSchema),
    defaultValues: { newPassword: "" },
  });

  const onSubmit = (values: ResetPasswordData) => {
    if (!user) return;
    resetPassword.mutate(
      { userId: user.id, newPassword: values.newPassword },
      {
        onSuccess: () => {
          toast.success("Password reset successfully");
          reset();
          onOpenChange(false);
        },
        onError: (error) => {
          toast.error(error.message || "Failed to reset password");
        },
      },
    );
  };

  const handleGenerate = () => {
    const password = generateStrongPassword();
    setValue("newPassword", password, { shouldValidate: true });
    setShowPassword(true);
  };

  const handleCopy = async () => {
    const field = document.querySelector<HTMLInputElement>('input[name="newPassword"]');
    if (field?.value) {
      await navigator.clipboard.writeText(field.value);
      toast.success("Password copied to clipboard");
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
          <DialogTitle>Reset password</DialogTitle>
          <DialogDescription>Set a new password for {user?.email}.</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
          <div>
            <label htmlFor="newPassword" className="block font-medium text-[13.5px] mb-1.5" style={{ color: "var(--ink)" }}>
              New password
            </label>
            <div className="flex gap-1.5">
              <div className="relative flex-1">
                <input
                  id="newPassword"
                  type={showPassword ? "text" : "password"}
                  className="af-input w-full pr-9"
                  aria-invalid={!!errors.newPassword}
                  {...register("newPassword")}
                />
                <button
                  type="button"
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded"
                  style={{ color: "var(--ink-4)" }}
                  onClick={() => setShowPassword((v) => !v)}
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff width={15} height={15} /> : <Eye width={15} height={15} />}
                </button>
              </div>
              <button
                type="button"
                className="af-btn"
                onClick={handleGenerate}
                title="Generate password"
              >
                <RefreshCw width={14} height={14} />
              </button>
              <button
                type="button"
                className="af-btn"
                onClick={() => void handleCopy()}
                title="Copy password"
              >
                <Copy width={14} height={14} />
              </button>
            </div>
            {errors.newPassword && (
              <p className="text-[12.5px] mt-1" style={{ color: "var(--err)" }}>
                {errors.newPassword.message}
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
              disabled={resetPassword.isPending}
            >
              {resetPassword.isPending ? "Resetting…" : "Reset"}
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
