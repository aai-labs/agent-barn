import { Suspense } from "react";

import { SetPasswordForm } from "@/auth/components/set-password-form";

export default function SetPasswordPage() {
  return (
    <div
      className="flex min-h-svh flex-col items-center justify-center p-6"
      style={{ background: "var(--bg)" }}
    >
      <Suspense fallback={null}>
        <SetPasswordForm />
      </Suspense>
    </div>
  );
}
