"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { strongPasswordSchema } from "@/auth/schemas";
import { EyeIcon, EyeOffIcon } from "@/components/icons";
import { LogoMark } from "@/components/logo-mark";
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

function AuthCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="w-full max-w-sm">
      <div
        className="rounded-2xl px-8 py-9"
        style={{
          background: "var(--bg-elev)",
          border: "1px solid var(--line)",
          boxShadow: "var(--shadow)",
        }}
      >
        <div className="mb-4 flex justify-center">
          <LogoMark size={36} />
        </div>
        {children}
      </div>
    </div>
  );
}

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
      <AuthCard>
        <div className="text-center">
          <h1
            className="m-0 mb-1 text-[22px] font-semibold tracking-tight"
            style={{ color: "var(--ink)" }}
          >
            {invalidTitle}
          </h1>
          <p className="m-0 text-[13.5px]" style={{ color: "var(--ink-3)" }}>
            {invalidSubtitle}
          </p>
          <Link
            href="/login"
            className="af-btn af-btn-primary af-btn-lg mt-6 w-full justify-center"
          >
            Back to login
          </Link>
        </div>
      </AuthCard>
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
        router.push("/login");
      })
      .catch((error) => {
        toast.error((error as ApiError).message || errorFallback);
      });
  };

  return (
    <AuthCard>
      <div className="mb-7 text-center">
        <h1
          className="m-0 mb-1 text-[22px] font-semibold tracking-tight"
          style={{ color: "var(--ink)" }}
        >
          {title}
        </h1>
        <p className="m-0 text-[13.5px]" style={{ color: "var(--ink-3)" }}>
          {subtitle}
        </p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
        {collectName && (
          <div>
            <label
              htmlFor="fullName"
              className="mb-1.5 block text-[13.5px] font-medium"
              style={{ color: "var(--ink)" }}
            >
              Full name
            </label>
            <input
              id="fullName"
              type="text"
              autoComplete="name"
              placeholder="Jane Doe"
              className="af-input w-full"
              aria-invalid={!!errors.fullName}
              {...register("fullName")}
            />
            {errors.fullName && (
              <p className="mt-1 text-[12.5px]" style={{ color: "var(--err)" }}>
                {errors.fullName.message}
              </p>
            )}
          </div>
        )}

        <div>
          <label
            htmlFor="newPassword"
            className="mb-1.5 block text-[13.5px] font-medium"
            style={{ color: "var(--ink)" }}
          >
            New password
          </label>
          <div className="relative">
            <input
              id="newPassword"
              type={showPassword ? "text" : "password"}
              className="af-input w-full pr-9"
              aria-invalid={!!errors.newPassword}
              {...register("newPassword")}
            />
            <button
              type="button"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5"
              style={{ color: "var(--ink-4)" }}
              onClick={() => setShowPassword((v) => !v)}
              tabIndex={-1}
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? <EyeOffIcon size={15} /> : <EyeIcon size={15} />}
            </button>
          </div>
          {errors.newPassword && (
            <p className="mt-1 text-[12.5px]" style={{ color: "var(--err)" }}>
              {errors.newPassword.message}
            </p>
          )}
        </div>

        <div>
          <label
            htmlFor="confirmPassword"
            className="mb-1.5 block text-[13.5px] font-medium"
            style={{ color: "var(--ink)" }}
          >
            Confirm password
          </label>
          <input
            id="confirmPassword"
            type={showPassword ? "text" : "password"}
            className="af-input w-full"
            aria-invalid={!!errors.confirmPassword}
            {...register("confirmPassword")}
          />
          {errors.confirmPassword && (
            <p className="mt-1 text-[12.5px]" style={{ color: "var(--err)" }}>
              {errors.confirmPassword.message}
            </p>
          )}
        </div>

        <button
          type="submit"
          disabled={isPending}
          className="af-btn af-btn-primary af-btn-lg mt-1 w-full justify-center"
        >
          {isPending ? pendingLabel : submitLabel}
        </button>
      </form>
    </AuthCard>
  );
}
