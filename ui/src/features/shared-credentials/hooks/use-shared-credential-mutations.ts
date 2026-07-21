"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { SharedCredentialReadSchema, type SharedCredentialRead } from "../schemas";
import { sharedCredentialsKey } from "../utils";

export type SharedCredentialCreatePayload = {
  provider: string;
  name: string;
  content: Record<string, string | string[]>;
};

export type SharedCredentialUpdatePayload = {
  credentialId: string;
  name?: string;
  content?: Record<string, string | string[]>;
};

export function useCreateSharedCredential() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ ...body }: SharedCredentialCreatePayload) => {
      const response = await api.post<SharedCredentialRead>(
        "/api/v1/shared-credentials",
        body,
        { schema: SharedCredentialReadSchema },
      );
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sharedCredentialsKey.all,
      });
    },
  });
}

export function useUpdateSharedCredential() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ credentialId, ...body }: SharedCredentialUpdatePayload) => {
      const response = await api.patch<SharedCredentialRead>(
        `/api/v1/shared-credentials/${credentialId}`,
        body,
        { schema: SharedCredentialReadSchema },
      );
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sharedCredentialsKey.all,
      });
    },
  });
}

export function useDeleteSharedCredential() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (credentialId: string) => {
      await api.delete(`/api/v1/shared-credentials/${credentialId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: sharedCredentialsKey.all,
      });
    },
  });
}

export function useValidateSharedCredential() {
  return useMutation({
    mutationFn: async (credentialId: string) => {
      const response = await api.post(
        `/api/v1/shared-credentials/${credentialId}/validate`,
        {},
      );
      return response.data;
    },
  });
}
