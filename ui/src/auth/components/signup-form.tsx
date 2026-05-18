"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { useAuthActions } from "@/auth/hooks/use-auth-actions";
import { SignupFormData, SignupFormSchema } from "@/auth/schemas";

export function SignupForm() {
  const router = useRouter();
  const { signup, isSigningUp } = useAuthActions();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<SignupFormData>({
    resolver: zodResolver(SignupFormSchema),
    defaultValues: { fullName: "", email: "", password: "", confirmPassword: "" },
  });

  const onSubmit = (values: SignupFormData) => {
    signup({
      email: values.email,
      fullName: values.fullName,
      password: values.password,
      onSuccess: () => {
        toast.success("Account created successfully.");
        router.push("/dashboard");
      },
      onError: (error) => {
        toast.error(error.message || "Unable to sign up.");
      },
    });
  };

  return (
    <div className="w-full max-w-sm">
      <div
        className="rounded-2xl px-8 py-9"
        style={{ background: "var(--bg-elev)", border: "1px solid var(--line)", boxShadow: "var(--shadow)" }}
      >
        <div className="text-center mb-7">
          <div
            className="w-9 h-9 rounded-xl grid place-items-center font-mono text-[14px] font-semibold text-white mx-auto mb-4"
            style={{ background: "var(--ink)" }}
          >
            AF
          </div>
          <h1 className="text-[22px] font-semibold tracking-tight m-0 mb-1" style={{ color: "var(--ink)" }}>
            Create your account
          </h1>
          <p className="text-[13.5px] m-0" style={{ color: "var(--ink-3)" }}>
            Enter your details to get started.
          </p>
        </div>

        <form onSubmit={handleSubmit(onSubmit)}>
          <div className="flex flex-col gap-4">
            <div>
              <label className="block font-medium text-[13.5px] mb-1.5" style={{ color: "var(--ink)" }}>
                Full name
              </label>
              <input
                id="name"
                type="text"
                placeholder="Jane Doe"
                className="af-input"
                aria-invalid={!!errors.fullName}
                {...register("fullName")}
              />
              {errors.fullName && (
                <p className="text-[12.5px] mt-1" style={{ color: "var(--err)" }}>
                  {errors.fullName.message}
                </p>
              )}
            </div>

            <div>
              <label className="block font-medium text-[13.5px] mb-1.5" style={{ color: "var(--ink)" }}>
                Email
              </label>
              <input
                id="email"
                type="email"
                placeholder="you@example.com"
                className="af-input"
                aria-invalid={!!errors.email}
                {...register("email")}
              />
              {errors.email && (
                <p className="text-[12.5px] mt-1" style={{ color: "var(--err)" }}>
                  {errors.email.message}
                </p>
              )}
            </div>

            <div>
              <label className="block font-medium text-[13.5px] mb-1.5" style={{ color: "var(--ink)" }}>
                Password
              </label>
              <input
                id="password"
                type="password"
                className="af-input"
                aria-invalid={!!errors.password}
                {...register("password")}
              />
              {errors.password && (
                <p className="text-[12.5px] mt-1" style={{ color: "var(--err)" }}>
                  {errors.password.message}
                </p>
              )}
            </div>

            <div>
              <label className="block font-medium text-[13.5px] mb-1.5" style={{ color: "var(--ink)" }}>
                Confirm password
              </label>
              <input
                id="confirm-password"
                type="password"
                className="af-input"
                aria-invalid={!!errors.confirmPassword}
                {...register("confirmPassword")}
              />
              {errors.confirmPassword && (
                <p className="text-[12.5px] mt-1" style={{ color: "var(--err)" }}>
                  {errors.confirmPassword.message}
                </p>
              )}
              <p className="text-[12.5px] mt-1.5" style={{ color: "var(--ink-4)" }}>
                Must be at least 8 characters.
              </p>
            </div>

            <button
              type="submit"
              disabled={isSigningUp}
              className="af-btn af-btn-primary af-btn-lg w-full justify-center mt-1"
            >
              {isSigningUp ? "Creating account…" : "Create account"}
            </button>
          </div>
        </form>

        <p className="text-center text-[13px] mt-5 m-0" style={{ color: "var(--ink-3)" }}>
          Already have an account?{" "}
          <Link href="/login" style={{ color: "var(--ink)", fontWeight: 500 }}>
            Log in
          </Link>
        </p>
      </div>

      <p className="text-center text-[12.5px] mt-5 px-4" style={{ color: "var(--ink-4)" }}>
        By continuing, you agree to our{" "}
        <Link href="#" style={{ color: "var(--ink-3)" }}>Terms of Service</Link>
        {" "}and{" "}
        <Link href="#" style={{ color: "var(--ink-3)" }}>Privacy Policy</Link>.
      </p>
    </div>
  );
}
