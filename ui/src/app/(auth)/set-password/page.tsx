import { Suspense } from "react";

import { SetPasswordForm } from "@/auth/components/set-password-form";

export default function SetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <SetPasswordForm />
    </Suspense>
  );
}
