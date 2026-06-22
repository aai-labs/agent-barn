"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { api } from "@/shared/api";
import { Token, TokenSchema } from "@/auth/schemas";
import { useAuthStore } from "@/auth/providers/auth-store";
import { strongPasswordSchema } from "@/auth/schemas";

const ChangePasswordSchema = z
  .object({
    oldPassword: z.string().min(1, { message: "Old password is required" }),
    newPassword: strongPasswordSchema,
    confirmNewPassword: z.string().min(1, { message: "Confirm your new password" }),
  })
  .refine((data) => data.newPassword === data.confirmNewPassword, {
    message: "Passwords do not match",
    path: ["confirmNewPassword"],
  });

type ChangePasswordData = z.infer<typeof ChangePasswordSchema>;

export default function AccountPage() {
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
      const response = await api.post<Token>("/api/v1/auth/me/change-password", {
        old_password: values.oldPassword,
        new_password: values.newPassword,
      }, { schema: TokenSchema });
      useAuthStore.getState().setToken(response.data);
      toast.success("Password changed successfully");
      reset();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to change password");
    }
  };

  return (
    <div className="max-w-[520px] mx-auto px-10 pt-9 pb-24">
      <h1 className="text-[22px] font-semibold mb-1" style={{ color: "var(--ink)" }}>
        Account
      </h1>
      <p className="text-[14px] mb-8" style={{ color: "var(--ink-3)" }}>
        Manage your account settings.
      </p>

      <div className="af-card px-6 py-5">
        <h2 className="text-[16px] font-semibold mb-4" style={{ color: "var(--ink)" }}>
          Change password
        </h2>

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

          <div className="flex justify-end mt-1">
            <button
              type="submit"
              className="af-btn af-btn-primary"
              disabled={isSubmitting}
            >
              {isSubmitting ? "Changing…" : "Change password"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
