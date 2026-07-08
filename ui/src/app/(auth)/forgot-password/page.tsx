import { ForgotPasswordForm } from "@/auth/components/forgot-password-form";

export default function ForgotPasswordPage() {
  return (
    <div
      className="flex min-h-svh flex-col items-center justify-center p-6"
      style={{ background: "var(--bg)" }}
    >
      <ForgotPasswordForm />
    </div>
  );
}
