"use client";

import Link from "next/link";
import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { useForgotPassword } from "@/auth/hooks/use-forgot-password";
import { LogoMark } from "@/components/logo-mark";

const ForgotPasswordSchema = z.object({
  email: z.string().email({ message: "Enter a valid email address" }),
});

type ForgotPasswordData = z.infer<typeof ForgotPasswordSchema>;

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
      <AuthCard>
        <div className="text-center">
          <h1
            className="m-0 mb-1 text-[22px] font-semibold tracking-tight"
            style={{ color: "var(--ink)" }}
          >
            Check your email
          </h1>
          <p className="m-0 text-[13.5px]" style={{ color: "var(--ink-3)" }}>
            If an account exists for{" "}
            <span style={{ color: "var(--ink)" }}>{submittedEmail}</span>, we&apos;ve
            sent a link to reset your password.
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

  return (
    <AuthCard>
      <div className="mb-7 text-center">
        <h1
          className="m-0 mb-1 text-[22px] font-semibold tracking-tight"
          style={{ color: "var(--ink)" }}
        >
          Forgot your password?
        </h1>
        <p className="m-0 text-[13.5px]" style={{ color: "var(--ink-3)" }}>
          Enter your email and we&apos;ll send you a reset link.
        </p>
      </div>

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
            autoComplete="email"
            className="af-input w-full"
            aria-invalid={!!errors.email}
            {...register("email")}
          />
          {errors.email && (
            <p className="mt-1 text-[12.5px]" style={{ color: "var(--err)" }}>
              {errors.email.message}
            </p>
          )}
        </div>

        <button
          type="submit"
          disabled={forgotPassword.isPending}
          className="af-btn af-btn-primary af-btn-lg mt-1 w-full justify-center"
        >
          {forgotPassword.isPending ? "Sending…" : "Send reset link"}
        </button>

        <Link
          href="/login"
          className="text-center text-[12.5px]"
          style={{ color: "var(--ink-3)" }}
        >
          Back to login
        </Link>
      </form>
    </AuthCard>
  );
}
