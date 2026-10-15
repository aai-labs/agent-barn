"use client";

import Link from "next/link";
import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AuthField, AuthFrame } from "@/auth/components/auth-frame";
import { useForgotPassword } from "@/auth/hooks/use-forgot-password";

const ForgotPasswordSchema = z.object({
  email: z.string().email({ message: "Enter a valid email address" }),
});

type ForgotPasswordData = z.infer<typeof ForgotPasswordSchema>;

export function ForgotPasswordForm() {
  const forgotPassword = useForgotPassword();
  const [submittedEmail, setSubmittedEmail] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ForgotPasswordData>({
    resolver: zodResolver(ForgotPasswordSchema),
    defaultValues: { email: "" },
  });

  const onSubmit = (values: ForgotPasswordData) => {
    // Always show the same confirmation regardless of whether the account exists.
    forgotPassword.mutate(
      { email: values.email },
      { onSettled: () => setSubmittedEmail(values.email) },
    );
  };

  if (submittedEmail) {
    return (
      <AuthFrame
        title="Check your email"
        subtitle={
          <>
            If an account exists for <span style={{ color: "var(--ink)" }}>{submittedEmail}</span>, we&apos;ve
            sent a link to reset your password.
          </>
        }
      >
        <Link href="/login?method=email" className="af-btn af-btn-primary af-btn-lg w-full justify-center">
          Back to login
        </Link>
      </AuthFrame>
    );
  }

  return (
    <AuthFrame title="Forgot your password?" subtitle="Enter your email and we'll send you a reset link.">
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
        <AuthField id="email" label="Email" error={errors.email?.message}>
          <input
            id="email"
            type="email"
            autoComplete="email"
            className="af-input"
            aria-invalid={!!errors.email}
            autoFocus
            {...register("email")}
          />
        </AuthField>
        <div className="mt-2 flex items-center gap-3">
          <Link href="/login?method=email" className="af-btn af-btn-ghost af-btn-lg">
            ← Back to login
          </Link>
          <button type="submit" disabled={forgotPassword.isPending} className="af-btn af-btn-primary af-btn-lg ml-auto">
            {forgotPassword.isPending ? "Sending…" : "Send reset link"}
          </button>
        </div>
      </form>
    </AuthFrame>
  );
}
