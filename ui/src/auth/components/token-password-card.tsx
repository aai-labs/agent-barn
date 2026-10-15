"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { AuthField, AuthFrame } from "@/auth/components/auth-frame";
import { strongPasswordSchema } from "@/auth/schemas";
import { EyeIcon, EyeOffIcon } from "@/components/icons";
import type { ApiError } from "@/shared/api/error/errors";

function makeSchema(collectName: boolean) {
  return z
    .object({
      fullName: collectName
        ? z.string().min(1, { message: "Enter your name" })
        : z.string(),
      newPassword: strongPasswordSchema,
      confirmPassword: z.string().min(1, { message: "Confirm your password" }),
    })
    .refine((data) => data.newPassword === data.confirmPassword, {
      message: "Passwords do not match",
      path: ["confirmPassword"],
    });
}

type TokenPasswordFormData = {
  fullName: string;
  newPassword: string;
  confirmPassword: string;
};

export interface TokenPasswordCardProps {
  /** Heading + subtext for the form state. */
  title: string;
  subtitle: string;
  /** Submit button labels. */
  submitLabel: string;
  pendingLabel: string;
  /** Toast shown on success, before redirecting to /login. */
  successMessage: string;
  /** Copy for the missing-token state. */
  invalidTitle: string;
  invalidSubtitle: string;
  /** Fallback toast when the request fails without a message. */
  errorFallback: string;
  /** When true, collect the user's (required) name — invite acceptance sets it. */
  collectName?: boolean;
  /** Runs the mutation for the given token + password (+ name on invite acceptance). */
  run: (vars: {
    token: string;
    newPassword: string;
    fullName?: string;
  }) => Promise<unknown>;
  isPending: boolean;
}

/**
 * Shared card for the two token-driven "choose a password" flows — accepting an invite
 * (set-password) and resetting a forgotten password. Both read a one-time token from the
 * URL, validate a new password, and return the user to /login on success.
 */
export function TokenPasswordCard({
  title,
  subtitle,
  submitLabel,
  pendingLabel,
  successMessage,
  invalidTitle,
  invalidSubtitle,
  errorFallback,
  collectName = false,
  run,
  isPending,
}: TokenPasswordCardProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [showPassword, setShowPassword] = useState(false);

  const schema = useMemo(() => makeSchema(collectName), [collectName]);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<TokenPasswordFormData>({
    resolver: zodResolver(schema),
    defaultValues: { fullName: "", newPassword: "", confirmPassword: "" },
  });

  if (!token) {
    return (
      <AuthFrame title={invalidTitle} subtitle={invalidSubtitle}>
        <Link href="/login?method=email" className="af-btn af-btn-primary af-btn-lg w-full justify-center">
          Back to login
        </Link>
      </AuthFrame>
    );
  }

  const onSubmit = (values: TokenPasswordFormData) => {
    void run({
      token,
      newPassword: values.newPassword,
      fullName: collectName ? values.fullName : undefined,
    })
      .then(() => {
        toast.success(successMessage);
        router.push("/login?method=email");
      })
      .catch((error) => {
        toast.error((error as ApiError).message || errorFallback);
      });
  };

  return (
    <AuthFrame title={title} subtitle={subtitle}>
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
        {collectName && (
          <AuthField id="fullName" label="Full name" error={errors.fullName?.message}>
            <input
              id="fullName"
              type="text"
              autoComplete="name"
              placeholder="Jane Doe"
              className="af-input"
              aria-invalid={!!errors.fullName}
              {...register("fullName")}
            />
          </AuthField>
        )}

        <AuthField id="newPassword" label="New password" error={errors.newPassword?.message}>
          <div className="relative">
            <input
              id="newPassword"
              type={showPassword ? "text" : "password"}
              autoComplete="new-password"
              className="af-input pr-9"
              aria-invalid={!!errors.newPassword}
              {...register("newPassword")}
            />
            <button
              type="button"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5"
              style={{ color: "var(--ink-4)" }}
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? <EyeOffIcon size={15} /> : <EyeIcon size={15} />}
            </button>
          </div>
        </AuthField>

        <AuthField id="confirmPassword" label="Confirm password" error={errors.confirmPassword?.message}>
          <input
            id="confirmPassword"
            type={showPassword ? "text" : "password"}
            autoComplete="new-password"
            className="af-input"
            aria-invalid={!!errors.confirmPassword}
            {...register("confirmPassword")}
          />
        </AuthField>

        <div className="mt-2 flex items-center gap-3">
          <Link href="/login?method=email" className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>
            Back to login
          </Link>
          <button type="submit" disabled={isPending} className="af-btn af-btn-primary af-btn-lg ml-auto">
            {isPending ? pendingLabel : submitLabel}
          </button>
        </div>
      </form>
    </AuthFrame>
  );
}
