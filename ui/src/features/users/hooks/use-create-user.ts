"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import {
  type PlatformUserCreateForm,
  PlatformUserCreateResultSchema,
  PlatformUserInviteResultSchema,
} from "../schemas";
import { usersKey } from "../utils";

export function useCreateUser() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: PlatformUserCreateForm) => {
      const response = await api.post(
        "/api/v1/platform/users",
        {
          email: data.email,
          fullName: data.fullName || undefined,
          organizationName: data.organizationName || undefined,
        },
        { schema: PlatformUserCreateResultSchema },
      );
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: usersKey.lists() });
    },
  });
}

export function useResendUserInvite() {
  return useMutation({
    mutationFn: async (userId: string) => {
      const response = await api.post(
        `/api/v1/platform/users/${userId}/resend-invite`,
        undefined,
        { schema: PlatformUserInviteResultSchema },
      );
      return response.data;
    },
  });
}
