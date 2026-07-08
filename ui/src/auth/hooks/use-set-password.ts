"use client";

import { useMutation } from "@tanstack/react-query";

import { api } from "@/shared/api";

/**
 * Completes an invite: sets the user's password and verifies their email via the
 * one-time token from the invite link. Unauthenticated (skipAuth).
 */
export function useSetPassword() {
  return useMutation({
    mutationFn: ({
      token,
      newPassword,
      fullName,
    }: {
      token: string;
      newPassword: string;
      fullName?: string;
    }) =>
      api.post(
        "/api/v1/auth/set-password",
        { token, newPassword, fullName },
        { skipAuth: true },
      ),
  });
}
