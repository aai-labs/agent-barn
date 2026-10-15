"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { AuthField, AuthFrame } from "@/auth/components/auth-frame";
import { useAuthActions } from "@/auth/hooks/use-auth-actions";
import { LoginFormData, LoginSchema } from "@/auth/schemas";
import { GoogleSignInButton, SignInError } from "@/features/onboarding/components/google-sign-in";

/**
 * The one front door, at /login and /signup: Google signs anyone in (and signs someone new
 * up for a trial); a password logs in an existing account.
 */
export function LoginForm({
  signInError,
  origin,
}: {
  signInError?: string | null;
  origin: "login" | "signup";
}) {
  const router = useRouter();
  const { login, isLoggingIn } = useAuthActions();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormData>({
    resolver: zodResolver(LoginSchema),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = (values: LoginFormData) => {
    login({
      email: values.email,
      password: values.password,
      onSuccess: () => {
        toast.success("Logged in successfully.");
        router.push("/dashboard");
      },
      onError: (error) => {
        toast.error(error.message || "Unable to login.");
      },
    });
  };

  return (
    <AuthFrame title="Welcome to Agent Barn" subtitle="Log in, or sign up with Google to start a free trial.">
      <div className="flex flex-col gap-2.5">
        <SignInError code={signInError} />
        <GoogleSignInButton origin={origin} />
      </div>

      <div className="my-5 flex items-center gap-3 text-[12px]" style={{ color: "var(--ink-4)" }}>
        <span className="h-px flex-1" style={{ background: "var(--line)" }} />
        or log in with your password
        <span className="h-px flex-1" style={{ background: "var(--line)" }} />
      </div>
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
        <AuthField id="email" label="Email" error={errors.email?.message}>
          <input
            id="email"
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            className="af-input"
            aria-invalid={!!errors.email}
            autoFocus
            {...register("email")}
          />
        </AuthField>
        <AuthField
          id="password"
          label="Password"
          error={errors.password?.message}
          aside={
            <Link href="/forgot-password" className="text-[12.5px]" style={{ color: "var(--accent-ink)" }}>
              Forgot password?
            </Link>
          }
        >
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            className="af-input"
            aria-invalid={!!errors.password}
            {...register("password")}
          />
        </AuthField>
        <button type="submit" disabled={isLoggingIn} className="af-btn af-btn-primary af-btn-lg w-full justify-center">
          {isLoggingIn ? "Logging in…" : "Log in"}
        </button>
      </form>
    </AuthFrame>
  );
}
