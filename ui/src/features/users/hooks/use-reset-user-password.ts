"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { usersKey } from "../utils";

export function useResetUserPassword() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ userId, newPassword }: { userId: string; newPassword: string }) => {
      await api.post(`/api/v1/users/${userId}/reset-password`, {
        new_password: newPassword,
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: usersKey.lists() });
    },
  });
}
