"use client";

import { useMutation } from "@tanstack/react-query";

import { api } from "@/shared/api";

/**
 * Resets a forgotten password using the one-time token from the reset email. Does not
 * verify email (unlike the invite flow). Unauthenticated (skipAuth).
 */
export function useResetPassword() {
  return useMutation({
    mutationFn: ({ token, newPassword }: { token: string; newPassword: string }) =>
      api.post(
        "/api/v1/auth/reset-password",
        { token, newPassword },
        { skipAuth: true },
      ),
  });
}
