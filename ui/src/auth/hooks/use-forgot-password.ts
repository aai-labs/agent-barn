"use client";

import { useMutation } from "@tanstack/react-query";

import { api } from "@/shared/api";

/**
 * Requests a password-reset email. The backend responds the same whether or not the
 * email exists (no account enumeration). Unauthenticated (skipAuth).
 */
export function useForgotPassword() {
  return useMutation({
    mutationFn: ({ email }: { email: string }) =>
      api.post("/api/v1/auth/forgot-password", { email }, { skipAuth: true }),
  });
}
