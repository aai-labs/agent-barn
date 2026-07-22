"use client";

import { useResetPassword } from "@/auth/hooks/use-reset-password";
import { TokenPasswordCard } from "@/auth/components/token-password-card";

export function ResetPasswordForm() {
  const resetPassword = useResetPassword();

  return (
    <TokenPasswordCard
      title="Reset your password"
      subtitle="Choose a new password for your account."
      submitLabel="Reset password"
      pendingLabel="Resetting…"
      successMessage="Password updated. Please log in to continue."
      invalidTitle="Invalid reset link"
      invalidSubtitle="This link is missing its token. Request a new password reset from the login page."
      errorFallback="This reset link is invalid or has expired."
      run={resetPassword.mutateAsync}
      isPending={resetPassword.isPending}
    />
  );
}
