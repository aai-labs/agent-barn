import { Suspense } from "react";

import { ResetPasswordForm } from "@/auth/components/reset-password-form";

export default function ResetPasswordPage() {
  return (
    <div
      className="flex min-h-svh flex-col items-center justify-center p-6"
      style={{ background: "var(--bg)" }}
    >
      <Suspense fallback={null}>
        <ResetPasswordForm />
      </Suspense>
    </div>
  );
}
