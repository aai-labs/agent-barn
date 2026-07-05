"use client";

import { useSetPassword } from "@/auth/hooks/use-set-password";
import { TokenPasswordCard } from "@/auth/components/token-password-card";

export function SetPasswordForm() {
  const setPassword = useSetPassword();

  return (
    <TokenPasswordCard
      collectName
      title="Set your password"
      subtitle="Choose a password to finish setting up your account."
      submitLabel="Set password"
      pendingLabel="Setting password…"
      successMessage="Password set. Please log in to continue."
      invalidTitle="Invalid invite link"
      invalidSubtitle="This link is missing its token. Ask your administrator to resend the invitation."
      errorFallback="This invite link is invalid or has expired."
      run={setPassword.mutateAsync}
      isPending={setPassword.isPending}
    />
  );
}
